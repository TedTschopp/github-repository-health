"""Offline and adversarial tests for selector-bound delivery collectors."""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
from urllib.error import HTTPError

from automation.repository_health.delivery_collectors import (
    ADAPTER_BATCH_VERIFICATION_SCHEMA,
    AUTHENTICATED_ADAPTER_SCHEMA,
    COLLECTOR_SCHEMA,
    DEPLOYMENT_PAYLOAD_SCHEMA,
    DeliveryCollectorError,
    HARD_MAX_ASSET_BYTES,
    HARD_MAX_TOTAL_ASSET_BYTES,
    collect_delivery_observations,
)
from automation.repository_health.delivery_resolution import (
    ANCESTRY_FACT_SCHEMA,
    STATEMENT_VERIFICATION_SCHEMA,
    resolve_delivery,
)
from automation.repository_health.evidence_producer import create_evidence_statement
from automation.repository_health.github_client import GitHubRESTClient
from automation.repository_health.production_identity import (
    ACTIVE_PROFILES,
    ARCHIVE_MAIN_POLICY,
    GENERIC_PRODUCTION_SCHEMA,
    MAIN_AHEAD_POLICY,
    NO_OUTPUT_MAIN_POLICY,
    validate_generic_production_identity,
)


ROOT = Path(__file__).resolve().parents[1]
API = "https://api.example"
REPOSITORY = "example/delivery-collector"
VERSION = "0.1.0-draft"
SOURCE_SHA = "a" * 40
MAIN_SHA = "b" * 40
WORKFLOW_SHA = "c" * 40
CONTENT_DIGEST = "d" * 64
SOURCE_DIGEST = "e" * 64
CHECK = "Validate Main"
PACKAGE_BYTES = b"bounded immutable package bytes\n"
PACKAGE_DIGEST = hashlib.sha256(PACKAGE_BYTES).hexdigest()


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

    def read(self, amount: int = -1) -> bytes:
        body = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return body if amount < 0 else body[:amount]

    def geturl(self) -> str | None:
        return self.url

    def close(self) -> None:
        return None

    def __enter__(self) -> "FixtureResponse":
        return self

    def __exit__(self, *arguments: object) -> bool:
        self.close()
        return False


class FixtureTransport:
    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: int) -> FixtureResponse:
        self.requests.append(request)
        url = request.full_url  # type: ignore[attr-defined]
        value = self.routes.get(url)
        if value is None:
            raise AssertionError(f"Unexpected fixture URL: {url}")
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            value = value(request, timeout)
        if not isinstance(value, FixtureResponse):
            raise AssertionError(f"Invalid fixture value: {value!r}")
        return value


def _url(path: str) -> str:
    return f"{API}{path}"


def _error(path: str, status: int) -> HTTPError:
    return HTTPError(_url(path), status, "fixture", {}, None)


def _client(routes: dict[str, object]) -> tuple[GitHubRESTClient, FixtureTransport]:
    transport = FixtureTransport(routes)
    return GitHubRESTClient(api_url=API, transport=transport), transport


def _validation(profile: str) -> dict:
    if profile in ACTIVE_PROFILES:
        reachable = True
        policy = MAIN_AHEAD_POLICY
    elif profile == "archived-retired":
        reachable = True
        policy = ARCHIVE_MAIN_POLICY
    else:
        reachable = False
        policy = NO_OUTPUT_MAIN_POLICY
    return {
        "authoritative_checks": [CHECK],
        "source_must_be_reachable_from_main": reachable,
        "main_ahead_policy": policy,
        "system_of_record_proof_required": True,
        "incomplete_system_of_record_result": "Unknown",
    }


def _unit(
    profile: str,
    *,
    unit_id: str = "unit",
    selector_id: int | str | None = None,
    source_sha: str = SOURCE_SHA,
    digest: str = CONTENT_DIGEST,
    asset_name: str = "package-2.4.0.tar.gz",
    package_digest: str = PACKAGE_DIGEST,
) -> dict:
    unit = {
        "unit_id": unit_id,
        "profile": profile,
        "lifecycle": "Active",
        "correspondence": (
            "Production-Ref" if profile == "gitops-production-ref" else "Exact-Main"
        ),
        "source_sha": source_sha,
        "validation": _validation(profile),
        "limitations": [],
    }
    if profile == "application-github-deployment":
        deployment_id = selector_id or 401
        unit["selector"] = {
            "system": "github-deployments",
            "strategy": "exact-deployment-id",
            "environment": "production",
            "deployment_id": deployment_id,
            "required_status": "success",
            "artifact": {
                "reference": f"ghcr.io/example/{unit_id}@sha256:{digest}",
                "sha256": digest,
            },
        }
    elif profile == "package-github-release":
        release_id = selector_id or 501
        unit["selector"] = {
            "system": "github-releases",
            "strategy": "exact-release-id-and-tag",
            "release_id": release_id,
            "tag": f"v2.4.{release_id - 501}",
            "allow_draft": False,
            "allow_prerelease": False,
            "artifacts": [
                {"name": asset_name, "sha256": package_digest, "primary": True}
            ],
        }
    elif profile == "gitops-production-ref":
        unit["selector"] = {
            "system": "git",
            "strategy": "exact-ref-commit-and-path",
            "production_ref": f"refs/heads/production-{unit_id}",
            "ref_commit_sha": source_sha,
            "path": f"environments/{unit_id}",
            "content_sha256": digest,
        }
    elif profile == "documentation-publication":
        deployment_id = selector_id or 601
        unit["selector"] = {
            "system": "github-pages",
            "strategy": "exact-pages-deployment-id",
            "environment": "github-pages",
            "deployment_id": deployment_id,
            "publication_url": f"https://docs.example.invalid/{unit_id}/",
            "content_sha256": digest,
            "required_status": "success",
        }
    elif profile == "approved-no-current-output":
        unit.update(
            {
                "lifecycle": "Experimental",
                "correspondence": "N/A",
                "source_sha": None,
                "selector": {
                    "system": "governance-decision",
                    "strategy": "approved-no-current-output",
                    "decision_id": "DEC-42",
                    "approved_by": "Architecture Review Board",
                    "approved_at": "2026-08-01",
                    "review_date": "2026-11-01",
                    "reason": "No output exists.",
                    "consumer_discovery": "No supported consumers were found.",
                },
            }
        )
    else:
        raise AssertionError(profile)
    return unit


def _identity(units: list[dict]) -> dict:
    correspondences = {unit["correspondence"] for unit in units}
    configured = next(iter(correspondences)) if len(correspondences) == 1 else "Per-unit combination"
    record = {
        "schema_version": GENERIC_PRODUCTION_SCHEMA,
        "standard_version": VERSION,
        "repository": REPOSITORY,
        "units": units,
    }
    config = {
        "standard": {"version": VERSION},
        "repository": {
            "authoritative_checks": [CHECK],
            "deployable_units": [unit["unit_id"] for unit in units],
            "production_correspondence": configured,
        },
    }
    return validate_generic_production_identity(record, config=config, repository=REPOSITORY)


def _adapter(unit: dict, kind: str, binding: dict, source_id: str) -> dict:
    return {
        "schema_version": AUTHENTICATED_ADAPTER_SCHEMA,
        "adapter_id": kind,
        "record_id": f"record-{unit['unit_id']}-{kind}",
        "repository": REPOSITORY,
        "unit_id": unit["unit_id"],
        "profile": unit["profile"],
        "source_sha": unit["source_sha"],
        "state": "verified",
        "population_complete": True,
        "authoritative_source_id": source_id,
        "authentication": {
            "state": "verified",
            "verifier": "trusted-offline-fixture",
            "evidence_ids": [source_id],
        },
        "binding": binding,
    }


def _adapter_batch(records: list[dict]) -> dict:
    canonical = json.dumps(
        records,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return {
        "schema_version": ADAPTER_BATCH_VERIFICATION_SCHEMA,
        "state": "verified",
        "population_complete": True,
        "verifier": "trusted-offline-adapter-fixture",
        "records_sha256": hashlib.sha256(canonical).hexdigest(),
        "matched_record_ids": sorted(record["record_id"] for record in records),
    }


def _application_routes(unit: dict) -> dict[str, object]:
    selector = unit["selector"]
    deployment_id = selector["deployment_id"]
    deployment_path = f"/repos/{REPOSITORY}/deployments/{deployment_id}"
    statuses_path = f"{deployment_path}/statuses?per_page=100"
    return {
        _url(deployment_path): FixtureResponse(
            {
                "id": deployment_id,
                "sha": unit["source_sha"],
                "ref": "main",
                "task": "deploy",
                "environment": selector["environment"],
                "payload": {
                    "schema_version": DEPLOYMENT_PAYLOAD_SCHEMA,
                    "unit_id": unit["unit_id"],
                    "artifact": deepcopy(selector["artifact"]),
                },
            }
        ),
        _url(statuses_path): FixtureResponse(
            [
                {
                    "id": deployment_id + 1_000,
                    "state": "success",
                    "environment": selector["environment"],
                }
            ]
        ),
    }


def _package_routes(
    unit: dict,
    *,
    annotated: bool = False,
    package_bytes: bytes = PACKAGE_BYTES,
) -> dict[str, object]:
    selector = unit["selector"]
    release_id = selector["release_id"]
    tag = selector["tag"]
    asset = selector["artifacts"][0]
    package_digest = asset["sha256"]
    if hashlib.sha256(package_bytes).hexdigest() != package_digest:
        raise AssertionError("package fixture bytes do not match the declared digest")
    asset_id = release_id + 1_000
    release_path = f"/repos/{REPOSITORY}/releases/{release_id}"
    assets_path = f"{release_path}/assets?per_page=100"
    ref_path = f"/repos/{REPOSITORY}/git/ref/tags/{tag}"
    binary_path = f"/repos/{REPOSITORY}/releases/assets/{asset_id}"
    attestation_path = (
        f"/repos/{REPOSITORY}/attestations/sha256:{package_digest}?per_page=100"
    )
    tag_sha = "f" * 40
    routes: dict[str, object] = {
        _url(release_path): FixtureResponse(
            {
                "id": release_id,
                "tag_name": tag,
                "target_commitish": "main",
                "draft": False,
                "prerelease": False,
                "immutable": True,
                "published_at": "2026-08-01T00:00:00Z",
            }
        ),
        _url(assets_path): FixtureResponse(
            [
                {
                    "id": asset_id,
                    "name": asset["name"],
                    "digest": f"sha256:{package_digest}",
                    "size": len(package_bytes),
                    "state": "uploaded",
                }
            ]
        ),
        _url(ref_path): FixtureResponse(
            {
                "ref": f"refs/tags/{tag}",
                "object": {
                    "type": "tag" if annotated else "commit",
                    "sha": tag_sha if annotated else unit["source_sha"],
                },
            }
        ),
        _url(binary_path): FixtureResponse(
            package_bytes,
            headers={"Content-Length": str(len(package_bytes))},
            url=_url(binary_path),
        ),
        _url(attestation_path): FixtureResponse(
            {
                "attestations": [
                    {
                        "id": release_id + 2_000,
                        "repository_id": 99,
                        "bundle_url": "https://objects.example/signed?secret=redacted",
                    }
                ],
            }
        ),
    }
    if annotated:
        routes[_url(f"/repos/{REPOSITORY}/git/tags/{tag_sha}")] = FixtureResponse(
            {
                "sha": tag_sha,
                "object": {"type": "commit", "sha": unit["source_sha"]},
            }
        )
    return routes


def _pages_routes(unit: dict, build_id: int) -> dict[str, object]:
    selector = unit["selector"]
    deployment_id = selector["deployment_id"]
    return {
        _url(f"/repos/{REPOSITORY}/pages/deployments/{deployment_id}"): FixtureResponse(
            {"status": "succeed"}
        ),
        _url(f"/repos/{REPOSITORY}/pages"): FixtureResponse(
            {"html_url": selector["publication_url"], "status": "built"}
        ),
        _url(f"/repos/{REPOSITORY}/pages/builds/{build_id}"): FixtureResponse(
            {
                "url": f"{API}/repos/{REPOSITORY}/pages/builds/{build_id}",
                "status": "built",
                "commit": unit["source_sha"],
            }
        ),
    }


def _application_proof(unit: dict, source_id: str) -> tuple[dict, dict, dict]:
    statement = create_evidence_statement(
        repository=REPOSITORY,
        unit_id=unit["unit_id"],
        subject_ref="refs/heads/main",
        subject_sha=SOURCE_SHA,
        subject_digests=[
            {"name": "source-tree", "algorithm": "sha256", "value": SOURCE_DIGEST}
        ],
        workflow_ref=f"{REPOSITORY}/.github/workflows/deploy.yml@refs/heads/main",
        workflow_sha=WORKFLOW_SHA,
        run_id=1001,
        run_attempt=1,
        kind="deployment",
        result="success",
        categories=["repository-health.application-production"],
        artifact_digests=[
            {
                "name": "application-artifact",
                "algorithm": "sha256",
                "value": CONTENT_DIGEST,
            }
        ],
        source_evidence_ids=[source_id],
    )
    verification = {
        "schema_version": STATEMENT_VERIFICATION_SCHEMA,
        "statement_id": statement["statement_id"],
        "repository": REPOSITORY,
        "unit_id": unit["unit_id"],
        "source_sha": SOURCE_SHA,
        "state": "verified",
        "population_complete": True,
        "matched_authoritative_source_ids": [source_id],
        "source_binding_complete": True,
        "result_binding_complete": True,
        "artifact_binding_complete": True,
        "category_policy_verified": True,
    }
    ancestry = {
        "schema_version": ANCESTRY_FACT_SCHEMA,
        "repository": REPOSITORY,
        "unit_id": unit["unit_id"],
        "source_sha": SOURCE_SHA,
        "main_sha": SOURCE_SHA,
        "state": "verified",
        "population_complete": True,
        "reachable_from_main": True,
    }
    return statement, verification, ancestry


def _ancestry_fact(unit: dict) -> dict:
    return {
        "schema_version": ANCESTRY_FACT_SCHEMA,
        "repository": REPOSITORY,
        "unit_id": unit["unit_id"],
        "source_sha": unit["source_sha"],
        "main_sha": SOURCE_SHA,
        "state": "verified",
        "population_complete": True,
        "reachable_from_main": True,
    }


def _package_proof(unit: dict) -> tuple[dict, dict]:
    release_id = unit["selector"]["release_id"]
    source_id = f"github-release:{release_id}"
    statement = create_evidence_statement(
        repository=REPOSITORY,
        unit_id=unit["unit_id"],
        subject_ref=f"refs/tags/{unit['selector']['tag']}",
        subject_sha=unit["source_sha"],
        subject_digests=[
            {"name": "source-tree", "algorithm": "sha256", "value": SOURCE_DIGEST}
        ],
        workflow_ref=f"{REPOSITORY}/.github/workflows/release.yml@refs/heads/main",
        workflow_sha=WORKFLOW_SHA,
        run_id=10_000 + release_id,
        run_attempt=1,
        kind="release",
        result="success",
        categories=["repository-health.package-release"],
        artifact_digests=[
            {
                "name": artifact["name"],
                "algorithm": "sha256",
                "value": artifact["sha256"],
            }
            for artifact in unit["selector"]["artifacts"]
        ],
        source_evidence_ids=[source_id],
    )
    verification = {
        "schema_version": STATEMENT_VERIFICATION_SCHEMA,
        "statement_id": statement["statement_id"],
        "repository": REPOSITORY,
        "unit_id": unit["unit_id"],
        "source_sha": unit["source_sha"],
        "state": "verified",
        "population_complete": True,
        "matched_authoritative_source_ids": [source_id],
        "source_binding_complete": True,
        "result_binding_complete": True,
        "artifact_binding_complete": True,
        "category_policy_verified": True,
    }
    return statement, verification


class DeliveryCollectorProfileTests(unittest.TestCase):
    def test_application_emits_resolver_ready_exact_deployment(self) -> None:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        client, _transport = _client(_application_routes(unit))

        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )

        self.assertEqual(COLLECTOR_SCHEMA, result["schema_version"])
        self.assertEqual("observed", result["state"])
        item = result["delivery_observation"]["data"]["inventory"]["items"][0]
        self.assertEqual(unit["unit_id"], item["unit_selector"])
        self.assertEqual(unit["selector"]["artifact"], item["artifact"])
        self.assertEqual("success", item["status"]["terminal_state"])
        self.assertEqual(
            "github-deployment-status:401:1401", item["authoritative_source_id"]
        )

    def test_application_output_resolves_only_with_separate_verified_statement(self) -> None:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        client, _transport = _client(_application_routes(unit))
        collected = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        source_id = "github-deployment-status:401:1401"
        statement, verification, ancestry = _application_proof(unit, source_id)
        resolved = resolve_delivery(
            identity,
            delivery_observation=collected["delivery_observation"],
            refs_releases_observation=collected["refs_releases_observation"],
            attestation_observation=collected["attestation_observation"],
            evidence_statements=[statement],
            statement_verifications=[verification],
            exact_main_sha=SOURCE_SHA,
            ancestry_facts=[ancestry],
            intervening_check_facts=[],
        )
        self.assertEqual("resolved", resolved["units"][0]["state"])

    def test_package_collects_exact_tag_assets_bytes_and_attestation_metadata(self) -> None:
        unit = _unit("package-github-release")
        identity = _identity([unit])
        client, _transport = _client(_package_routes(unit, annotated=True))
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
            max_asset_bytes=1024,
        )

        release = result["refs_releases_observation"]["data"]["releases"][0]
        self.assertTrue(release["tag_target"]["peel_complete"])
        self.assertEqual(SOURCE_SHA, release["tag_target"]["peeled_sha"])
        self.assertEqual(
            PACKAGE_BYTES,
            result["refs_releases_observation"]["data"]["asset_contents_by_release"]
            [f"501:package-2.4.0.tar.gz:{PACKAGE_DIGEST}"],
        )
        self.assertEqual(
            {}, result["refs_releases_observation"]["data"]["asset_contents"]
        )
        attestation = result["attestation_observation"]["data"]["assets"][0]
        self.assertEqual("501:package-2.4.0.tar.gz", attestation["asset_key"])
        self.assertTrue(attestation["attestations"][0]["bundle_url_present"])
        self.assertNotIn("bundle_url", attestation["attestations"][0])
        self.assertIsNone(attestation["source_binding"])

    def test_package_follows_official_attestation_cursor_without_total_count(self) -> None:
        unit = _unit("package-github-release")
        identity = _identity([unit])
        routes = _package_routes(unit)
        first_path = (
            f"/repos/{REPOSITORY}/attestations/sha256:{PACKAGE_DIGEST}?per_page=100"
        )
        second_url = f"{_url(first_path)}&after=cursor-1"
        routes[_url(first_path)] = FixtureResponse(
            {
                "attestations": [
                    {
                        "repository_id": 99,
                        "bundle_url": "https://objects.example/first",
                    }
                ]
            },
            headers={"Link": f'<{second_url}>; rel="next"'},
        )
        routes[second_url] = FixtureResponse(
            {
                "attestations": [
                    {
                        "repository_id": 99,
                        "bundle_url": "https://objects.example/second",
                    }
                ]
            }
        )
        client, transport = _client(routes)
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        attestation = result["attestation_observation"]
        self.assertTrue(attestation["population_complete"])
        self.assertEqual(2, len(attestation["data"]["assets"][0]["attestations"]))
        self.assertIn(second_url, [request.full_url for request in transport.requests])

    def test_gitops_requires_authenticated_exact_reconciliation_binding(self) -> None:
        unit = _unit("gitops-production-ref")
        identity = _identity([unit])
        relative = unit["selector"]["production_ref"].removeprefix("refs/")
        path = f"/repos/{REPOSITORY}/git/ref/{relative}"
        client, _transport = _client(
            {
                _url(path): FixtureResponse(
                    {
                        "ref": unit["selector"]["production_ref"],
                        "object": {"type": "commit", "sha": SOURCE_SHA},
                    }
                )
            }
        )
        source_id = f"gitops-reconciliation:{unit['unit_id']}:{SOURCE_SHA}"
        adapter = _adapter(
            unit,
            "gitops-reconciliation",
            {
                "production_ref": unit["selector"]["production_ref"],
                "path": unit["selector"]["path"],
                "content_sha256": CONTENT_DIGEST,
            },
            source_id,
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=MAIN_SHA,
            client=client,
            authenticated_adapter_records=[adapter],
            adapter_batch_verification=_adapter_batch([adapter]),
        )
        row = result["refs_releases_observation"]["data"]["remote_refs"][0]
        self.assertEqual(unit["unit_id"], row["unit_selector"])
        self.assertEqual(CONTENT_DIGEST, row["content"]["sha256"])
        self.assertEqual(source_id, row["reconciliation"]["authoritative_source_id"])

    def test_pages_uses_official_status_shape_exact_build_and_content_binding(self) -> None:
        unit = _unit("documentation-publication")
        identity = _identity([unit])
        build_id = 9_001
        client, _transport = _client(_pages_routes(unit, build_id))
        source_id = f"pages-publication:{unit['unit_id']}:{SOURCE_SHA}"
        adapter = _adapter(
            unit,
            "pages-publication",
            {
                "deployment_id": unit["selector"]["deployment_id"],
                "build_id": build_id,
                "publication_url": unit["selector"]["publication_url"],
                "content_sha256": CONTENT_DIGEST,
            },
            source_id,
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
            authenticated_adapter_records=[adapter],
            adapter_batch_verification=_adapter_batch([adapter]),
        )
        item = result["delivery_observation"]["data"]["inventory"]["items"][0]
        self.assertEqual({"status": "succeed"}, item["status"])
        self.assertNotIn("terminal_status_id", item["status"])
        self.assertEqual(SOURCE_SHA, item["source_sha"])
        self.assertEqual(CONTENT_DIGEST, item["publication"]["content_sha256"])
        self.assertEqual("github-pages-deployment:601", item["authoritative_source_id"])

    def test_pages_preserves_and_quotes_exact_sha_deployment_id(self) -> None:
        unit = _unit(
            "documentation-publication",
            selector_id=SOURCE_SHA,
        )
        identity = _identity([unit])
        build_id = 9_002
        client, transport = _client(_pages_routes(unit, build_id))
        binding_source = f"pages-publication:{unit['unit_id']}:{SOURCE_SHA}"
        adapter = _adapter(
            unit,
            "pages-publication",
            {
                "deployment_id": SOURCE_SHA,
                "build_id": build_id,
                "publication_url": unit["selector"]["publication_url"],
                "content_sha256": CONTENT_DIGEST,
            },
            binding_source,
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
            authenticated_adapter_records=[adapter],
            adapter_batch_verification=_adapter_batch([adapter]),
        )
        item = result["delivery_observation"]["data"]["inventory"]["items"][0]
        self.assertEqual(SOURCE_SHA, item["selectors"]["deployment_id"])
        self.assertEqual(
            f"github-pages-deployment:{SOURCE_SHA}", item["authoritative_source_id"]
        )
        self.assertIn(
            _url(f"/repos/{REPOSITORY}/pages/deployments/{SOURCE_SHA}"),
            [request.full_url for request in transport.requests],
        )


class DeliveryCollectorFailClosedTests(unittest.TestCase):
    def test_missing_or_malformed_deployment_payload_remains_unknown(self) -> None:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        routes = _application_routes(unit)
        deployment_url = _url(f"/repos/{REPOSITORY}/deployments/401")
        routes[deployment_url] = FixtureResponse(
            {
                "id": 401,
                "sha": SOURCE_SHA,
                "environment": "production",
                "payload": '{"schema_version":"wrong","unit_id":"unit","artifact":{}}',
            }
        )
        client, _transport = _client(routes)
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn(
            "deployment_artifact_binding_missing",
            {gap["code"] for gap in result["gaps"]},
        )

    def test_semantic_deployment_mismatch_cannot_be_laundered_into_resolution(self) -> None:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        routes = _application_routes(unit)
        deployment_url = _url(f"/repos/{REPOSITORY}/deployments/401")
        bad_deployment = deepcopy(routes[deployment_url].payload)  # type: ignore[union-attr]
        bad_deployment["id"] = 999
        routes[deployment_url] = FixtureResponse(bad_deployment)
        client, _transport = _client(routes)
        collected = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        self.assertEqual("unknown", collected["delivery_observation"]["state"])
        source_id = "github-deployment-status:401:1401"
        statement, verification, ancestry = _application_proof(unit, source_id)
        resolved = resolve_delivery(
            identity,
            delivery_observation=collected["delivery_observation"],
            refs_releases_observation=collected["refs_releases_observation"],
            attestation_observation=collected["attestation_observation"],
            evidence_statements=[statement],
            statement_verifications=[verification],
            exact_main_sha=SOURCE_SHA,
            ancestry_facts=[ancestry],
            intervening_check_facts=[],
        )
        self.assertEqual("unknown", resolved["units"][0]["state"])

    def test_mutated_nested_identity_is_rejected_before_api_access(self) -> None:
        identity = _identity([_unit("application-github-deployment")])
        del identity["units"][0]["selector"]["environment"]
        client, transport = _client({})
        with self.assertRaises(DeliveryCollectorError):
            collect_delivery_observations(
                identity,
                repository=REPOSITORY,
                subject_main_sha=SOURCE_SHA,
                client=client,
            )
        self.assertEqual([], transport.requests)

    def test_permission_gap_is_unknown_and_preserves_no_fabricated_item(self) -> None:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        deployment = f"/repos/{REPOSITORY}/deployments/401"
        statuses = f"{deployment}/statuses?per_page=100"
        client, _transport = _client(
            {
                _url(deployment): _error(deployment, 403),
                _url(statuses): _error(statuses, 403),
            }
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        self.assertEqual("unknown", result["state"])
        self.assertFalse(result["delivery_observation"]["population_complete"])
        self.assertEqual([], result["delivery_observation"]["data"]["inventory"]["items"])
        self.assertIn("permission_or_api_gap", {gap["code"] for gap in result["gaps"]})

    def test_gitops_declaration_alone_never_creates_reconciliation(self) -> None:
        unit = _unit("gitops-production-ref")
        identity = _identity([unit])
        relative = unit["selector"]["production_ref"].removeprefix("refs/")
        path = f"/repos/{REPOSITORY}/git/ref/{relative}"
        client, _transport = _client(
            {
                _url(path): FixtureResponse(
                    {
                        "ref": unit["selector"]["production_ref"],
                        "object": {"type": "commit", "sha": SOURCE_SHA},
                    }
                )
            }
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=MAIN_SHA,
            client=client,
        )
        row = result["refs_releases_observation"]["data"]["remote_refs"][0]
        self.assertIsNone(row["content"])
        self.assertIsNone(row["reconciliation"])
        self.assertIn(
            "authenticated_adapter_ambiguous", {gap["code"] for gap in result["gaps"]}
        )

    def test_self_asserted_adapter_record_without_batch_verification_is_unknown(self) -> None:
        unit = _unit("gitops-production-ref")
        identity = _identity([unit])
        relative = unit["selector"]["production_ref"].removeprefix("refs/")
        path = f"/repos/{REPOSITORY}/git/ref/{relative}"
        client, _transport = _client(
            {
                _url(path): FixtureResponse(
                    {
                        "ref": unit["selector"]["production_ref"],
                        "object": {"type": "commit", "sha": SOURCE_SHA},
                    }
                )
            }
        )
        source_id = f"gitops-reconciliation:{unit['unit_id']}:{SOURCE_SHA}"
        record = _adapter(
            unit,
            "gitops-reconciliation",
            {
                "production_ref": unit["selector"]["production_ref"],
                "path": unit["selector"]["path"],
                "content_sha256": CONTENT_DIGEST,
            },
            source_id,
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=MAIN_SHA,
            client=client,
            authenticated_adapter_records=[record],
        )
        row = result["refs_releases_observation"]["data"]["remote_refs"][0]
        self.assertIsNone(row["reconciliation"])
        self.assertEqual("unknown", result["adapter_trust"]["state"])
        self.assertIn(
            "authenticated_adapter_batch_unverified",
            {gap["code"] for gap in result["gaps"]},
        )

    def test_unverified_or_unknown_key_adapter_record_is_rejected(self) -> None:
        unit = _unit("gitops-production-ref")
        identity = _identity([unit])
        relative = unit["selector"]["production_ref"].removeprefix("refs/")
        path = f"/repos/{REPOSITORY}/git/ref/{relative}"
        client, _transport = _client(
            {
                _url(path): FixtureResponse(
                    {
                        "ref": unit["selector"]["production_ref"],
                        "object": {"type": "commit", "sha": SOURCE_SHA},
                    }
                )
            }
        )
        source_id = f"gitops-reconciliation:{unit['unit_id']}:{SOURCE_SHA}"
        adapter = _adapter(
            unit,
            "gitops-reconciliation",
            {
                "production_ref": unit["selector"]["production_ref"],
                "path": unit["selector"]["path"],
                "content_sha256": CONTENT_DIGEST,
            },
            source_id,
        )
        adapter["trusted"] = True
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=MAIN_SHA,
            client=client,
            authenticated_adapter_records=[adapter],
            adapter_batch_verification=_adapter_batch([adapter]),
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn(
            "invalid_authenticated_adapter_record",
            {gap["code"] for gap in result["gaps"]},
        )

    def test_duplicate_authenticated_adapter_claims_are_ambiguous(self) -> None:
        unit = _unit("gitops-production-ref")
        identity = _identity([unit])
        relative = unit["selector"]["production_ref"].removeprefix("refs/")
        path = f"/repos/{REPOSITORY}/git/ref/{relative}"
        client, _transport = _client(
            {
                _url(path): FixtureResponse(
                    {
                        "ref": unit["selector"]["production_ref"],
                        "object": {"type": "commit", "sha": SOURCE_SHA},
                    }
                )
            }
        )
        source_id = f"gitops-reconciliation:{unit['unit_id']}:{SOURCE_SHA}"
        adapter = _adapter(
            unit,
            "gitops-reconciliation",
            {
                "production_ref": unit["selector"]["production_ref"],
                "path": unit["selector"]["path"],
                "content_sha256": CONTENT_DIGEST,
            },
            source_id,
        )
        records = [adapter, deepcopy(adapter)]
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=MAIN_SHA,
            client=client,
            authenticated_adapter_records=records,
            adapter_batch_verification=_adapter_batch(records),
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn(
            "authenticated_adapter_ambiguous",
            {gap["code"] for gap in result["gaps"]},
        )

    def test_pages_permission_or_missing_content_binding_remains_unknown(self) -> None:
        unit = _unit("documentation-publication")
        identity = _identity([unit])
        status = f"/repos/{REPOSITORY}/pages/deployments/601"
        site = f"/repos/{REPOSITORY}/pages"
        client, _transport = _client(
            {
                _url(status): _error(status, 403),
                _url(site): FixtureResponse(
                    {"html_url": unit["selector"]["publication_url"]}
                ),
            }
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        self.assertEqual("unknown", result["state"])
        item = result["delivery_observation"]["data"]["inventory"]["items"][0]
        self.assertIsNone(item["publication"])
        self.assertIsNone(item["source_sha"])

    def test_pages_extra_status_fields_or_wrong_build_url_fail_closed(self) -> None:
        unit = _unit("documentation-publication")
        identity = _identity([unit])
        build_id = 9_003
        routes = _pages_routes(unit, build_id)
        status_url = _url(f"/repos/{REPOSITORY}/pages/deployments/601")
        build_url = _url(f"/repos/{REPOSITORY}/pages/builds/{build_id}")
        routes[status_url] = FixtureResponse(
            {"status": "succeed", "invented_status_id": 123}
        )
        routes[build_url] = FixtureResponse(
            {
                "url": f"{API}/repos/{REPOSITORY}/pages/builds/999999",
                "status": "built",
                "commit": SOURCE_SHA,
            }
        )
        client, _transport = _client(routes)
        source_id = f"pages-publication:{unit['unit_id']}:{SOURCE_SHA}"
        adapter = _adapter(
            unit,
            "pages-publication",
            {
                "deployment_id": 601,
                "build_id": build_id,
                "publication_url": unit["selector"]["publication_url"],
                "content_sha256": CONTENT_DIGEST,
            },
            source_id,
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
            authenticated_adapter_records=[adapter],
            adapter_batch_verification=_adapter_batch([adapter]),
        )
        self.assertEqual("unknown", result["delivery_observation"]["state"])
        self.assertTrue(
            {"pages_deployment_not_successful", "pages_build_source_mismatch"}
            <= {gap["code"] for gap in result["gaps"]}
        )

    def test_documentation_github_deployment_subtype_is_explicitly_unsupported(self) -> None:
        unit = _unit("documentation-publication")
        unit["selector"].update(
            {
                "system": "github-deployments",
                "strategy": "exact-deployment-id",
                "environment": "documentation-production",
            }
        )
        identity = _identity([unit])
        client, transport = _client({})
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        self.assertEqual([], transport.requests)
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn(
            "documentation_delivery_system_unsupported",
            {gap["code"] for gap in result["gaps"]},
        )

    def test_multi_unit_selectors_and_bytes_do_not_bleed(self) -> None:
        first = _unit(
            "application-github-deployment", unit_id="first", selector_id=411, digest="1" * 64
        )
        second = _unit(
            "application-github-deployment", unit_id="second", selector_id=412, digest="2" * 64
        )
        identity = _identity([first, second])
        routes = {**_application_routes(first), **_application_routes(second)}
        client, _transport = _client(routes)
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        items = result["delivery_observation"]["data"]["inventory"]["items"]
        by_unit = {item["unit_selector"]: item for item in items}
        self.assertEqual("1" * 64, by_unit["first"]["artifact"]["sha256"])
        self.assertEqual("2" * 64, by_unit["second"]["artifact"]["sha256"])
        self.assertEqual({"first", "second"}, set(by_unit))

    def test_application_permission_gap_does_not_poison_resolvable_sibling(self) -> None:
        broken = _unit(
            "application-github-deployment", unit_id="broken", selector_id=411
        )
        healthy = _unit(
            "application-github-deployment", unit_id="healthy", selector_id=412
        )
        routes = _application_routes(healthy)
        broken_deployment = f"/repos/{REPOSITORY}/deployments/411"
        broken_statuses = f"{broken_deployment}/statuses?per_page=100"
        routes.update(
            {
                _url(broken_deployment): _error(broken_deployment, 403),
                _url(broken_statuses): _error(broken_statuses, 403),
            }
        )
        identity = _identity([broken, healthy])
        client, _transport = _client(routes)
        collected = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        source_id = "github-deployment-status:412:1412"
        statement, verification, _ancestry = _application_proof(healthy, source_id)
        resolved = resolve_delivery(
            identity,
            delivery_observation=collected["delivery_observation"],
            refs_releases_observation=collected["refs_releases_observation"],
            attestation_observation=collected["attestation_observation"],
            evidence_statements=[statement],
            statement_verifications=[verification],
            exact_main_sha=SOURCE_SHA,
            ancestry_facts=[_ancestry_fact(broken), _ancestry_fact(healthy)],
            intervening_check_facts=[],
        )
        states = {row["unit_id"]: row["state"] for row in resolved["units"]}
        self.assertEqual("unknown", states["broken"])
        self.assertEqual("resolved", states["healthy"])

    def test_package_attestation_gap_does_not_poison_resolvable_sibling(self) -> None:
        broken_bytes = b"first immutable package bytes\n"
        broken_digest = hashlib.sha256(broken_bytes).hexdigest()
        broken = _unit(
            "package-github-release",
            unit_id="broken-package",
            selector_id=501,
            asset_name="package.tar.gz",
            package_digest=broken_digest,
        )
        healthy = _unit(
            "package-github-release",
            unit_id="healthy-package",
            selector_id=502,
            asset_name="package.tar.gz",
        )
        routes = {
            **_package_routes(broken, package_bytes=broken_bytes),
            **_package_routes(healthy),
        }
        broken_attestations = (
            f"/repos/{REPOSITORY}/attestations/sha256:{broken_digest}?per_page=100"
        )
        routes[_url(broken_attestations)] = _error(broken_attestations, 403)
        identity = _identity([broken, healthy])
        client, _transport = _client(routes)
        collected = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        statement, verification = _package_proof(healthy)
        resolved = resolve_delivery(
            identity,
            delivery_observation=collected["delivery_observation"],
            refs_releases_observation=collected["refs_releases_observation"],
            attestation_observation=collected["attestation_observation"],
            evidence_statements=[statement],
            statement_verifications=[verification],
            exact_main_sha=SOURCE_SHA,
            ancestry_facts=[_ancestry_fact(broken), _ancestry_fact(healthy)],
            intervening_check_facts=[],
        )
        states = {row["unit_id"]: row["state"] for row in resolved["units"]}
        self.assertEqual("unknown", states["broken-package"])
        self.assertEqual("resolved", states["healthy-package"])

    def test_same_package_filename_across_releases_resolves_without_bleed(self) -> None:
        first = _unit(
            "package-github-release",
            unit_id="first-package",
            selector_id=501,
            asset_name="package.tar.gz",
        )
        second = _unit(
            "package-github-release",
            unit_id="second-package",
            selector_id=502,
            asset_name="package.tar.gz",
        )
        identity = _identity([first, second])
        client, _transport = _client(
            {**_package_routes(first), **_package_routes(second)}
        )
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        refs = result["refs_releases_observation"]
        self.assertEqual("observed", refs["state"])
        self.assertEqual({}, refs["data"]["asset_contents"])
        release_keys = set(refs["data"]["asset_contents_by_release"])
        self.assertEqual(2, len(release_keys))
        self.assertTrue(all(key.endswith(f":{PACKAGE_DIGEST}") for key in release_keys))
        first_statement, first_verification = _package_proof(first)
        second_statement, second_verification = _package_proof(second)
        resolved = resolve_delivery(
            identity,
            delivery_observation=result["delivery_observation"],
            refs_releases_observation=refs,
            attestation_observation=result["attestation_observation"],
            evidence_statements=[first_statement, second_statement],
            statement_verifications=[first_verification, second_verification],
            exact_main_sha=SOURCE_SHA,
            ancestry_facts=[_ancestry_fact(first), _ancestry_fact(second)],
            intervening_check_facts=[],
        )
        self.assertEqual(
            ["resolved", "resolved"], [row["state"] for row in resolved["units"]]
        )

    def test_per_asset_and_total_binary_budgets_fail_closed(self) -> None:
        unit = _unit("package-github-release")
        identity = _identity([unit])
        client, transport = _client({})
        for arguments in (
            {"max_asset_bytes": HARD_MAX_ASSET_BYTES + 1},
            {"max_total_asset_bytes": HARD_MAX_TOTAL_ASSET_BYTES + 1},
        ):
            with self.assertRaises(DeliveryCollectorError):
                collect_delivery_observations(
                    identity,
                    repository=REPOSITORY,
                    subject_main_sha=SOURCE_SHA,
                    client=client,
                    **arguments,
                )
        self.assertEqual([], transport.requests)

        first = _unit(
            "package-github-release",
            unit_id="first-budget",
            selector_id=501,
            asset_name="first.tar.gz",
        )
        second = _unit(
            "package-github-release",
            unit_id="second-budget",
            selector_id=502,
            asset_name="second.tar.gz",
        )
        client, transport = _client(
            {**_package_routes(first), **_package_routes(second)}
        )
        result = collect_delivery_observations(
            _identity([first, second]),
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
            max_asset_bytes=1024,
            max_total_asset_bytes=len(PACKAGE_BYTES),
        )
        self.assertEqual(len(PACKAGE_BYTES), result["binary_collection"]["bytes_collected"])
        self.assertIn(
            "binary_collection_budget_exhausted",
            {gap["code"] for gap in result["gaps"]},
        )
        second_binary_url = _url(
            f"/repos/{REPOSITORY}/releases/assets/{second['selector']['release_id'] + 1000}"
        )
        self.assertNotIn(second_binary_url, [request.full_url for request in transport.requests])

    def test_duplicate_declared_selector_is_unknown_without_api_access(self) -> None:
        first = _unit("application-github-deployment", unit_id="first", selector_id=499)
        second = _unit("application-github-deployment", unit_id="second", selector_id=499)
        identity = _identity([first, second])
        client, transport = _client({})
        result = collect_delivery_observations(
            identity,
            repository=REPOSITORY,
            subject_main_sha=SOURCE_SHA,
            client=client,
        )
        self.assertEqual([], transport.requests)
        self.assertEqual(["unknown", "unknown"], [row["state"] for row in result["units"]])
        self.assertEqual(
            {"declared_selector_ambiguous"},
            {gap["code"] for gap in result["gaps"]},
        )

    def test_contract_errors_are_rejected_before_api_access(self) -> None:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        client, transport = _client({})
        with self.assertRaises(DeliveryCollectorError):
            collect_delivery_observations(
                identity,
                repository="different/repository",
                subject_main_sha=SOURCE_SHA,
                client=client,
            )
        with self.assertRaises(DeliveryCollectorError):
            collect_delivery_observations(
                identity,
                repository="../..",
                subject_main_sha=SOURCE_SHA,
                client=client,
            )
        with self.assertRaises(DeliveryCollectorError):
            collect_delivery_observations(
                identity,
                repository=REPOSITORY,
                subject_main_sha="main",
                client=client,
            )
        self.assertEqual([], transport.requests)

    def test_collector_has_no_execution_or_filesystem_mutation_imports(self) -> None:
        source = (
            ROOT / "automation" / "repository_health" / "delivery_collectors.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        self.assertTrue(
            imports.isdisjoint(
                {"subprocess", "os", "pathlib", "shutil", "runpy", "importlib"}
            )
        )


if __name__ == "__main__":
    unittest.main()

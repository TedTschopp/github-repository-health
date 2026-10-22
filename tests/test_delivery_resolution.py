"""Offline contract and adversarial tests for delivery resolution."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import unittest

from automation.repository_health.delivery_resolution import (
    ANCESTRY_FACT_SCHEMA,
    ATTESTATION_BINDING_SCHEMA,
    INTERVENING_CHECK_FACT_SCHEMA,
    POLICY_VERSION,
    PROFILE_POLICY,
    RESOLUTION_SCHEMA,
    STATEMENT_VERIFICATION_SCHEMA,
    DeliveryResolutionError,
    resolve_delivery,
)
from automation.repository_health.evidence_producer import create_evidence_statement
from automation.repository_health.production_identity import (
    ACTIVE_PROFILES,
    ARCHIVE_MAIN_POLICY,
    GENERIC_PRODUCTION_SCHEMA,
    MAIN_AHEAD_POLICY,
    NO_OUTPUT_MAIN_POLICY,
    validate_generic_production_identity,
)


REPOSITORY = "example/delivery-resolution"
VERSION = "0.1.0-draft"
SOURCE_SHA = "a" * 40
MAIN_SHA = "b" * 40
WORKFLOW_SHA = "c" * 40
CONTENT_DIGEST = "d" * 64
SOURCE_DIGEST = "e" * 64
CHECK = "Validate Main"
PACKAGE_BYTES = b"immutable package bytes\n"
PACKAGE_DIGEST = hashlib.sha256(PACKAGE_BYTES).hexdigest()


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
    correspondence: str | None = None,
    selector_id: int | None = None,
    digest: str = CONTENT_DIGEST,
) -> dict:
    chosen_correspondence = correspondence or (
        "Production-Ref" if profile == "gitops-production-ref" else "Exact-Main"
    )
    unit = {
        "unit_id": unit_id,
        "profile": profile,
        "lifecycle": "Active",
        "correspondence": chosen_correspondence,
        "source_sha": SOURCE_SHA,
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
            "tag": "v2.4.0",
            "allow_draft": False,
            "allow_prerelease": False,
            "artifacts": [
                {
                    "name": "package-2.4.0.tar.gz",
                    "sha256": PACKAGE_DIGEST,
                    "primary": True,
                }
            ],
        }
    elif profile == "gitops-production-ref":
        unit["selector"] = {
            "system": "git",
            "strategy": "exact-ref-commit-and-path",
            "production_ref": "refs/heads/production",
            "ref_commit_sha": SOURCE_SHA,
            "path": "environments/production",
            "content_sha256": digest,
        }
    elif profile == "documentation-publication":
        deployment_id = selector_id or 601
        unit["selector"] = {
            "system": "github-pages",
            "strategy": "exact-pages-deployment-id",
            "environment": "github-pages",
            "deployment_id": deployment_id,
            "publication_url": "https://docs.example.invalid/guide/",
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
                    "reason": "No supported output exists.",
                    "consumer_discovery": "Portfolio search found no supported consumer.",
                },
            }
        )
    elif profile == "archived-retired":
        unit.update(
            {
                "lifecycle": "Archived",
                "correspondence": "N/A",
                "source_sha": None,
                "selector": {
                    "system": "governance-decision",
                    "strategy": "archive-disposition",
                    "disposition": "Archived",
                    "decision_id": "RET-7",
                    "approved_by": "Portfolio Owner",
                    "effective_at": "2026-07-31",
                    "last_known_source_sha": SOURCE_SHA,
                    "last_known_output": {
                        "status": "none",
                        "kind": None,
                        "identity": None,
                        "reason": "No output was ever published.",
                    },
                    "write_protected": True,
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


def _statement(
    unit: dict,
    *,
    source_id: str,
    artifact_digests: list[dict],
    result: str = "success",
    category: str | None = None,
    kind: str | None = None,
) -> dict:
    policy = PROFILE_POLICY[unit["profile"]]
    if unit["profile"] == "package-github-release":
        subject_ref = f"refs/tags/{unit['selector']['tag']}"
    elif unit["profile"] == "gitops-production-ref":
        subject_ref = unit["selector"]["production_ref"]
    else:
        subject_ref = "refs/heads/main"
    return create_evidence_statement(
        repository=REPOSITORY,
        unit_id=unit["unit_id"],
        subject_ref=subject_ref,
        subject_sha=unit["source_sha"],
        subject_digests=[
            {"name": "source-tree", "algorithm": "sha256", "value": SOURCE_DIGEST}
        ],
        workflow_ref=f"{REPOSITORY}/.github/workflows/production.yml@refs/heads/main",
        workflow_sha=WORKFLOW_SHA,
        run_id=1001,
        run_attempt=1,
        kind=kind or policy["statement_kind"],
        result=result,
        categories=[category or policy["statement_category"]],
        artifact_digests=artifact_digests,
        source_evidence_ids=[source_id],
    )


def _verification(statement: dict, unit: dict, source_id: str, **overrides: object) -> dict:
    value = {
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
    value.update(overrides)
    return value


def _ancestry(unit: dict, main_sha: str) -> dict:
    return {
        "schema_version": ANCESTRY_FACT_SCHEMA,
        "repository": REPOSITORY,
        "unit_id": unit["unit_id"],
        "source_sha": unit["source_sha"],
        "main_sha": main_sha,
        "state": "verified",
        "population_complete": True,
        "reachable_from_main": True,
    }


def _intervening(unit: dict, main_sha: str, conclusion: str = "success") -> dict:
    revisions = []
    if unit["source_sha"] != main_sha:
        revisions = [
            {
                "sha": main_sha,
                "checks": [{"name": CHECK, "conclusion": conclusion}],
            }
        ]
    return {
        "schema_version": INTERVENING_CHECK_FACT_SCHEMA,
        "repository": REPOSITORY,
        "unit_id": unit["unit_id"],
        "source_sha": unit["source_sha"],
        "main_sha": main_sha,
        "state": "verified",
        "population_complete": True,
        "revisions": revisions,
    }


def _delivery_observation(adapter_id: str, items: list[dict], *, complete: bool = True) -> dict:
    return {
        "state": "observed" if complete else "unknown",
        "population_complete": complete,
        "data": {
            "inventory": {
                "schema_version": "RH-GITHUB-DELIVERY-INVENTORY-1.0",
                "repository": REPOSITORY,
                "observed_subject_sha": SOURCE_SHA,
                "adapters": [
                    {
                        "adapter_id": adapter_id,
                        "delivery_kind": "pages" if adapter_id == "github-pages" else "deployment",
                        "state": "observed" if complete else "unknown",
                        "population_complete": complete,
                        "repository_scope": "exact",
                        "selector_fields": ["deployment_id", "environment"],
                        "item_count": len(items),
                    }
                ],
                "items": items,
            }
        },
    }


def _deployment_item(unit: dict, *, documentation: bool = False) -> tuple[dict, str]:
    selector = unit["selector"]
    status_id = selector["deployment_id"] + 1_000
    if selector["system"] == "github-pages":
        source_id = f"github-pages-deployment:{selector['deployment_id']}"
        status = {"status": "succeed"}
    else:
        source_id = f"github-deployment-status:{selector['deployment_id']}:{status_id}"
        status = {
            "terminal_state": "success",
            "terminal_status_id": status_id,
            "population_complete": True,
        }
    item = {
        "inventory_id": f"{selector['system']}:{selector['deployment_id']}",
        "adapter_id": selector["system"],
        "delivery_kind": "pages" if documentation else "deployment",
        "repository": REPOSITORY,
        "unit_selector": unit["unit_id"],
        "selectors": {
            "deployment_id": selector["deployment_id"],
            "environment": selector["environment"],
        },
        "observed_subject_sha": SOURCE_SHA,
        "source_sha": unit["source_sha"],
        "matches_subject": True,
        "status": status,
        "authoritative_source_id": source_id,
    }
    if documentation:
        item["publication"] = {
            "url": selector["publication_url"],
            "content_sha256": selector["content_sha256"],
        }
    else:
        item["artifact"] = deepcopy(selector["artifact"])
    return item, source_id


def _refs_observation(*, rows: list[dict] | None = None, releases: list[dict] | None = None, contents: dict | None = None, complete: bool = True) -> dict:
    return {
        "state": "observed" if complete else "unknown",
        "population_complete": complete,
        "data": {
            "remote_refs": rows or [],
            "releases": releases or [],
            "asset_contents": contents or {},
        },
    }


def _base_call(
    identity: dict,
    *,
    delivery: dict | None = None,
    refs: dict | None = None,
    attestations: dict | None = None,
    statements: list[dict] | None = None,
    verifications: list[dict] | None = None,
    main_sha: str = SOURCE_SHA,
    ancestry: list[dict] | None = None,
    intervening: list[dict] | None = None,
) -> dict:
    units = identity["units"]
    return resolve_delivery(
        identity,
        delivery_observation=delivery,
        refs_releases_observation=refs,
        attestation_observation=attestations,
        evidence_statements=statements or [],
        statement_verifications=verifications or [],
        exact_main_sha=main_sha,
        ancestry_facts=ancestry if ancestry is not None else [
            _ancestry(unit, main_sha) for unit in units if unit["source_sha"] is not None
        ],
        intervening_check_facts=intervening if intervening is not None else [
            _intervening(unit, main_sha)
            for unit in units
            if unit["source_sha"] is not None and unit["correspondence"] == "Releasable-Main"
        ],
    )


class DeliveryResolutionProfileTests(unittest.TestCase):
    def test_application_resolves_with_exact_collector_bindings_and_main_ahead(self) -> None:
        unit = _unit("application-github-deployment", correspondence="Releasable-Main")
        identity = _identity([unit])
        item, source_id = _deployment_item(unit)
        item["unit_selector"] = None
        item["observed_subject_sha"] = MAIN_SHA
        item["matches_subject"] = False
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": CONTENT_DIGEST}
            ],
        )
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
            verifications=[_verification(statement, unit, source_id)],
            main_sha=MAIN_SHA,
        )
        self.assertEqual(RESOLUTION_SCHEMA, result["schema_version"])
        self.assertEqual(POLICY_VERSION, result["policy_version"])
        self.assertTrue(result["complete"])
        self.assertEqual("resolved", result["units"][0]["state"])
        self.assertTrue(result["units"][0]["traceable"])

    def test_documentation_pages_requires_exact_id_and_resolves(self) -> None:
        unit = _unit("documentation-publication")
        identity = _identity([unit])
        item, source_id = _deployment_item(unit, documentation=True)
        item["unit_selector"] = None
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "published-content", "algorithm": "sha256", "value": CONTENT_DIGEST}
            ],
        )
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-pages", [item]),
            statements=[statement],
            verifications=[_verification(statement, unit, source_id)],
        )
        self.assertEqual("resolved", result["units"][0]["state"])
        self.assertNotIn("terminal_status_id", item["status"])
        self.assertEqual(
            "github-pages-deployment:601",
            result["units"][0]["authoritative_source_ids"][0],
        )

    def test_gitops_ref_resolves_only_with_reconciliation_statement(self) -> None:
        unit = _unit("gitops-production-ref")
        identity = _identity([unit])
        source_id = f"gitops-reconciliation:{unit['unit_id']}:{SOURCE_SHA}"
        row = {
            "ref": unit["selector"]["production_ref"],
            "object": {"type": "commit", "sha": SOURCE_SHA},
            "source": "branch_ref",
            "unit_selector": None,
            "content": {
                "path": unit["selector"]["path"],
                "sha256": CONTENT_DIGEST,
            },
            "reconciliation": {
                "state": "success",
                "population_complete": True,
                "authoritative_source_id": source_id,
            },
        }
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "production-content", "algorithm": "sha256", "value": CONTENT_DIGEST}
            ],
        )
        result = _base_call(
            identity,
            refs=_refs_observation(rows=[row]),
            statements=[statement],
            verifications=[_verification(statement, unit, source_id)],
            main_sha=MAIN_SHA,
        )
        self.assertEqual("resolved", result["units"][0]["state"])

    def test_package_release_resolves_with_verified_release_statement(self) -> None:
        unit = _unit("package-github-release")
        identity = _identity([unit])
        source_id = "github-release:501"
        release = {
            "id": 501,
            "tag_name": "v2.4.0",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-01T00:00:00Z",
            "tag_target": {
                "peel_complete": True,
                "peeled_sha": SOURCE_SHA,
            },
            "assets": [
                {
                    "id": 701,
                    "name": "package-2.4.0.tar.gz",
                    "digest": f"sha256:{PACKAGE_DIGEST}",
                }
            ],
            "authoritative_source_id": source_id,
        }
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "package-2.4.0.tar.gz", "algorithm": "sha256", "value": PACKAGE_DIGEST}
            ],
        )
        result = _base_call(
            identity,
            refs=_refs_observation(
                releases=[release],
                contents={"package-2.4.0.tar.gz": PACKAGE_BYTES},
            ),
            statements=[statement],
            verifications=[_verification(statement, unit, source_id)],
        )
        self.assertEqual("resolved", result["units"][0]["state"])

    def test_package_can_use_verified_source_binding_attestation(self) -> None:
        unit = _unit("package-github-release")
        identity = _identity([unit])
        release = {
            "id": 501,
            "unit_selector": unit["unit_id"],
            "tag_name": "v2.4.0",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-01T00:00:00Z",
            "tag_target": {"peel_complete": True, "peeled_sha": SOURCE_SHA},
            "assets": [
                {
                    "id": 701,
                    "name": "package-2.4.0.tar.gz",
                    "digest": f"sha256:{PACKAGE_DIGEST}",
                }
            ],
            "authoritative_source_id": "github-release:501",
        }
        attestation_id = "github-attestation:bundle-701"
        attestation = {
            "state": "observed",
            "population_complete": True,
            "data": {
                "assets": [
                    {
                        "release_id": 501,
                        "asset_id": 701,
                        "name": "package-2.4.0.tar.gz",
                        "digest": f"sha256:{PACKAGE_DIGEST}",
                        "attestations": [{"id": "bundle-701"}],
                        "complete": True,
                        "unit_selector": unit["unit_id"],
                        "source_binding": {
                            "schema_version": ATTESTATION_BINDING_SCHEMA,
                            "state": "verified",
                            "repository": REPOSITORY,
                            "unit_id": unit["unit_id"],
                            "release_id": 501,
                            "asset_name": "package-2.4.0.tar.gz",
                            "artifact_sha256": PACKAGE_DIGEST,
                            "source_sha": SOURCE_SHA,
                            "population_complete": True,
                            "source_binding_complete": True,
                            "artifact_binding_complete": True,
                            "category_policy_verified": True,
                            "matched_authoritative_source_ids": [attestation_id],
                        },
                    }
                ]
            },
        }
        result = _base_call(
            identity,
            refs=_refs_observation(
                releases=[release],
                contents={"package-2.4.0.tar.gz": PACKAGE_BYTES},
            ),
            attestations=attestation,
        )
        self.assertEqual("resolved", result["units"][0]["state"])
        self.assertIn(attestation_id, result["units"][0]["authoritative_source_ids"])


class DeliveryResolutionFailClosedTests(unittest.TestCase):
    def _application_fixture(self) -> tuple[dict, dict, dict, str]:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        item, source_id = _deployment_item(unit)
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": CONTENT_DIGEST}
            ],
        )
        return identity, item, statement, source_id

    def test_bare_statement_never_passes(self) -> None:
        identity, item, statement, _source_id = self._application_fixture()
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("statement_verification_ambiguous", {gap["code"] for gap in result["gaps"]})

    def test_actions_run_success_cannot_authenticate_delivery_category(self) -> None:
        unit = _unit("application-github-deployment")
        identity = _identity([unit])
        item, _source_id = _deployment_item(unit)
        actions_source = "github-actions-run:1001:1"
        statement = _statement(
            unit,
            source_id=actions_source,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": CONTENT_DIGEST}
            ],
        )
        verification = _verification(statement, unit, actions_source)
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
            verifications=[verification],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("production_statement_mismatch", {gap["code"] for gap in result["gaps"]})

    def test_unbound_current_collector_row_and_pages_without_exact_id_stay_unknown(self) -> None:
        unit = _unit("documentation-publication")
        identity = _identity([unit])
        current_like = {
            "inventory_id": "github-pages:site",
            "adapter_id": "github-pages",
            "delivery_kind": "pages",
            "repository": REPOSITORY,
            "unit_selector": None,
            "selectors": {"html_url": unit["selector"]["publication_url"]},
            "observed_subject_sha": SOURCE_SHA,
            "source_sha": SOURCE_SHA,
            "matches_subject": True,
            "status": {
                "site": "built",
                "current_build": "built",
                "subject_deployment": "succeed",
            },
        }
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-pages", [current_like]),
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("deployment_selector_ambiguous", {gap["code"] for gap in result["gaps"]})

    def test_partial_adapter_population_never_passes(self) -> None:
        identity, item, statement, source_id = self._application_fixture()
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item], complete=False),
            statements=[statement],
            verifications=[_verification(statement, identity["units"][0], source_id)],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("delivery_adapter_incomplete", {gap["code"] for gap in result["gaps"]})

    def test_exact_authoritative_status_sha_or_artifact_mismatch_is_nonconforming(self) -> None:
        cases = {
            "terminal_status_success": lambda item: item["status"].update(
                {"terminal_state": "failure"}
            ),
            "source_sha_matches": lambda item: item.update({"source_sha": MAIN_SHA}),
            "artifact_identity_matches": lambda item: item["artifact"].update(
                {"sha256": "f" * 64}
            ),
        }
        for failed_component, mutate in cases.items():
            with self.subTest(component=failed_component):
                identity, item, statement, source_id = self._application_fixture()
                mutate(item)
                result = _base_call(
                    identity,
                    delivery=_delivery_observation("github-deployments", [item]),
                    statements=[statement],
                    verifications=[
                        _verification(statement, identity["units"][0], source_id)
                    ],
                )
                unit_result = result["units"][0]
                self.assertEqual("nonconforming", unit_result["state"])
                self.assertFalse(unit_result["traceable"])
                self.assertEqual("fail", unit_result["components"][failed_component])

    def test_evidence_gap_remains_unknown_not_nonconforming(self) -> None:
        identity, item, statement, _source_id = self._application_fixture()
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
            verifications=[],
        )
        unit_result = result["units"][0]
        self.assertEqual("unknown", unit_result["state"])
        self.assertIsNone(unit_result["traceable"])
        self.assertNotIn("fail", unit_result["components"].values())

    def test_unscoped_malformed_population_fails_all_units_unknown(self) -> None:
        first = _unit(
            "application-github-deployment", unit_id="first", selector_id=411
        )
        second = _unit(
            "application-github-deployment", unit_id="second", selector_id=412
        )
        identity = _identity([first, second])
        first_item, first_source = _deployment_item(first)
        second_item, second_source = _deployment_item(second)
        first_statement = _statement(
            first,
            source_id=first_source,
            artifact_digests=[
                {
                    "name": "application-artifact",
                    "algorithm": "sha256",
                    "value": CONTENT_DIGEST,
                }
            ],
        )
        second_statement = _statement(
            second,
            source_id=second_source,
            artifact_digests=[
                {
                    "name": "application-artifact",
                    "algorithm": "sha256",
                    "value": CONTENT_DIGEST,
                }
            ],
        )
        delivery = _delivery_observation(
            "github-deployments", [first_item, second_item]
        )
        inventory = delivery["data"]["inventory"]
        adapter = inventory["adapters"][0]
        inventory["population_scope"] = "per-unit"
        inventory["adapters"] = [
            {**adapter, "unit_selector": "first", "item_count": 1},
            {**adapter, "unit_selector": "second", "item_count": 1},
            dict(adapter),
        ]
        result = _base_call(
            identity,
            delivery=delivery,
            statements=[first_statement, second_statement],
            verifications=[
                _verification(first_statement, first, first_source),
                _verification(second_statement, second, second_source),
            ],
        )
        self.assertEqual(
            ["unknown", "unknown"], [row["state"] for row in result["units"]]
        )
        for row in result["units"]:
            self.assertIn(
                "delivery_population_unscoped",
                {gap["code"] for gap in row["gaps"]},
            )
            self.assertNotIn("fail", row["components"].values())

    def test_duplicate_delivery_rows_and_duplicate_statements_are_unknown(self) -> None:
        identity, item, statement, source_id = self._application_fixture()
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item, deepcopy(item)]),
            statements=[statement, deepcopy(statement)],
            verifications=[_verification(statement, identity["units"][0], source_id)],
        )
        codes = {gap["code"] for gap in result["gaps"]}
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("deployment_selector_ambiguous", codes)
        self.assertIn("duplicate_evidence_statement", codes)

    def test_false_category_or_artifact_collector_binding_is_unknown(self) -> None:
        identity, item, statement, source_id = self._application_fixture()
        verification = _verification(
            statement,
            identity["units"][0],
            source_id,
            category_policy_verified=False,
            artifact_binding_complete=False,
        )
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
            verifications=[verification],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("statement_verification_incomplete", {gap["code"] for gap in result["gaps"]})

    def test_unknown_verification_key_is_rejected_fail_closed(self) -> None:
        identity, item, statement, source_id = self._application_fixture()
        verification = _verification(statement, identity["units"][0], source_id)
        verification["trusted"] = True
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
            verifications=[verification],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("invalid_statement_verification", {gap["code"] for gap in result["gaps"]})

    def test_malicious_unhashable_raw_values_become_unknown_instead_of_crashing(self) -> None:
        unit = _unit("application-github-deployment", correspondence="Releasable-Main")
        identity = _identity([unit])
        item, source_id = _deployment_item(unit)
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": CONTENT_DIGEST}
            ],
        )
        item["unit_selector"] = {"forged": "unit"}
        verification = _verification(statement, unit, source_id)
        verification["state"] = {"forged": "verified"}
        fact = _intervening(unit, MAIN_SHA)
        fact["revisions"] = [
            {
                "sha": MAIN_SHA,
                "checks": [{"name": {"forged": CHECK}, "conclusion": "success"}],
            }
        ]
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
            verifications=[verification],
            main_sha=MAIN_SHA,
            intervening=[fact],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        codes = {gap["code"] for gap in result["gaps"]}
        self.assertIn("deployment_unit_conflict", codes)
        self.assertIn("invalid_statement_verification", codes)
        self.assertIn("intervening_checks_unverified", codes)

    def test_failed_intervening_check_blocks_releasable_main_resolution(self) -> None:
        unit = _unit("application-github-deployment", correspondence="Releasable-Main")
        identity = _identity([unit])
        item, source_id = _deployment_item(unit)
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": CONTENT_DIGEST}
            ],
        )
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[statement],
            verifications=[_verification(statement, unit, source_id)],
            main_sha=MAIN_SHA,
            intervening=[_intervening(unit, MAIN_SHA, conclusion="failure")],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn("intervening_checks_unverified", {gap["code"] for gap in result["gaps"]})

    def test_corrupt_downloaded_release_bytes_are_nonconforming(self) -> None:
        unit = _unit("package-github-release")
        identity = _identity([unit])
        release = {
            "id": 501,
            "unit_selector": unit["unit_id"],
            "tag_name": "v2.4.0",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-01T00:00:00Z",
            "tag_target": {"peel_complete": True, "peeled_sha": SOURCE_SHA},
            "assets": [
                {"id": 701, "name": "package-2.4.0.tar.gz", "digest": f"sha256:{PACKAGE_DIGEST}"}
            ],
            "authoritative_source_id": "github-release:501",
        }
        result = _base_call(
            identity,
            refs=_refs_observation(
                releases=[release], contents={"package-2.4.0.tar.gz": b"tampered"}
            ),
        )
        self.assertEqual("nonconforming", result["units"][0]["state"])
        self.assertEqual(
            "fail", result["units"][0]["components"]["artifact_identity_matches"]
        )
        self.assertIn("release_artifact_mismatch", {gap["code"] for gap in result["gaps"]})

    def test_verified_attestation_conflict_blocks_valid_release_statement(self) -> None:
        unit = _unit("package-github-release")
        identity = _identity([unit])
        source_id = "github-release:501"
        release = {
            "id": 501,
            "tag_name": "v2.4.0",
            "draft": False,
            "prerelease": False,
            "published_at": "2026-08-01T00:00:00Z",
            "tag_target": {"peel_complete": True, "peeled_sha": SOURCE_SHA},
            "assets": [
                {"id": 701, "name": "package-2.4.0.tar.gz", "digest": f"sha256:{PACKAGE_DIGEST}"}
            ],
            "authoritative_source_id": source_id,
        }
        statement = _statement(
            unit,
            source_id=source_id,
            artifact_digests=[
                {"name": "package-2.4.0.tar.gz", "algorithm": "sha256", "value": PACKAGE_DIGEST}
            ],
        )
        conflicting_attestation = {
            "state": "observed",
            "population_complete": True,
            "data": {
                "assets": [
                    {
                        "release_id": 501,
                        "name": "package-2.4.0.tar.gz",
                        "digest": f"sha256:{PACKAGE_DIGEST}",
                        "source_binding": {
                            "schema_version": ATTESTATION_BINDING_SCHEMA,
                            "state": "verified",
                            "repository": REPOSITORY,
                            "unit_id": unit["unit_id"],
                            "release_id": 501,
                            "asset_name": "package-2.4.0.tar.gz",
                            "artifact_sha256": PACKAGE_DIGEST,
                            "source_sha": MAIN_SHA,
                            "population_complete": True,
                            "source_binding_complete": True,
                            "artifact_binding_complete": True,
                            "category_policy_verified": True,
                            "matched_authoritative_source_ids": ["github-attestation:conflict"],
                        },
                    }
                ]
            },
        }
        result = _base_call(
            identity,
            refs=_refs_observation(
                releases=[release], contents={"package-2.4.0.tar.gz": PACKAGE_BYTES}
            ),
            attestations=conflicting_attestation,
            statements=[statement],
            verifications=[_verification(statement, unit, source_id)],
        )
        self.assertEqual("unknown", result["units"][0]["state"])
        self.assertIn(
            "conflicting_verified_attestation",
            {gap["code"] for gap in result["gaps"]},
        )

    def test_inactive_profiles_remain_unknown_pending_governance_adapter(self) -> None:
        for profile in ("approved-no-current-output", "archived-retired"):
            with self.subTest(profile=profile):
                identity = _identity([_unit(profile)])
                result = _base_call(identity)
                self.assertEqual("unknown", result["units"][0]["state"])
                self.assertIn("governance_adapter_pending", {gap["code"] for gap in result["gaps"]})

    def test_multi_unit_evidence_is_isolated(self) -> None:
        first = _unit(
            "application-github-deployment",
            unit_id="first",
            selector_id=411,
            digest="1" * 64,
        )
        second = _unit(
            "application-github-deployment",
            unit_id="second",
            selector_id=412,
            digest="2" * 64,
        )
        identity = _identity([first, second])
        first_item, first_source = _deployment_item(first)
        second_item, second_source = _deployment_item(second)
        second_item["unit_selector"] = "first"
        first_statement = _statement(
            first,
            source_id=first_source,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": "1" * 64}
            ],
        )
        second_statement = _statement(
            second,
            source_id=second_source,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": "2" * 64}
            ],
        )
        result = _base_call(
            identity,
            delivery=_delivery_observation(
                "github-deployments", [first_item, second_item]
            ),
            statements=[first_statement, second_statement],
            verifications=[
                _verification(first_statement, first, first_source),
                _verification(second_statement, second, second_source),
            ],
        )
        states = {item["unit_id"]: item["state"] for item in result["units"]}
        self.assertEqual("resolved", states["first"])
        self.assertEqual("nonconforming", states["second"])
        self.assertEqual(
            "fail",
            next(row for row in result["units"] if row["unit_id"] == "second")[
                "components"
            ]["system_record_matches"],
        )
        first_codes = {gap["code"] for gap in result["units"][0]["gaps"]}
        self.assertNotIn("deployment_unit_conflict", first_codes)

    def test_duplicate_declared_selector_makes_every_claimant_unknown(self) -> None:
        first = _unit(
            "application-github-deployment",
            unit_id="first",
            selector_id=499,
            digest="1" * 64,
        )
        second = _unit(
            "application-github-deployment",
            unit_id="second",
            selector_id=499,
            digest="2" * 64,
        )
        identity = _identity([first, second])
        item, source_id = _deployment_item(first)
        item["unit_selector"] = None
        first_statement = _statement(
            first,
            source_id=source_id,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": "1" * 64}
            ],
        )
        second_statement = _statement(
            second,
            source_id=source_id,
            artifact_digests=[
                {"name": "application-artifact", "algorithm": "sha256", "value": "2" * 64}
            ],
        )
        result = _base_call(
            identity,
            delivery=_delivery_observation("github-deployments", [item]),
            statements=[first_statement, second_statement],
            verifications=[
                _verification(first_statement, first, source_id),
                _verification(second_statement, second, source_id),
            ],
        )
        self.assertEqual(["unknown", "unknown"], [unit["state"] for unit in result["units"]])
        for resolved_unit in result["units"]:
            self.assertIn(
                "declared_selector_ambiguous",
                {gap["code"] for gap in resolved_unit["gaps"]},
            )

    def test_non_v2_identity_is_a_caller_contract_error(self) -> None:
        with self.assertRaises(DeliveryResolutionError):
            resolve_delivery(
                {"schema_version": "RH-PRODUCTION-IDENTITY-1.0"},
                delivery_observation=None,
                refs_releases_observation=None,
                attestation_observation=None,
                evidence_statements=[],
                statement_verifications=[],
                exact_main_sha=None,
                ancestry_facts=[],
                intervening_check_facts=[],
            )


if __name__ == "__main__":
    unittest.main()

"""Round-trip tests for delivery resolution metric observations."""

from __future__ import annotations

from copy import deepcopy
import unittest

from automation.repository_health.delivery_metrics import apply_delivery_metrics
from automation.repository_health.delivery_resolution import (
    POLICY_VERSION,
    RESOLUTION_SCHEMA,
)
from automation.repository_health.measurements import calculate_metrics, gate_results
from automation.repository_health.production_identity import (
    ACTIVE_PROFILES,
    GENERIC_PRODUCTION_SCHEMA,
    MAIN_AHEAD_POLICY,
    validate_generic_production_identity,
)


NOW = "2026-08-09T20:00:00Z"
REPOSITORY = "example/delivery-metrics"
VERSION = "0.1.0-draft"
MAIN_SHA = "a" * 40
OLDER_SHA = "b" * 40
DIGEST = "c" * 64
CHECK = "Validate Main"


def _validation() -> dict:
    return {
        "authoritative_checks": [CHECK],
        "source_must_be_reachable_from_main": True,
        "main_ahead_policy": MAIN_AHEAD_POLICY,
        "system_of_record_proof_required": True,
        "incomplete_system_of_record_result": "Unknown",
    }


def _unit(
    unit_id: str,
    *,
    correspondence: str = "Exact-Main",
    source_sha: str = MAIN_SHA,
) -> dict:
    profile = (
        "gitops-production-ref"
        if correspondence == "Production-Ref"
        else "application-github-deployment"
    )
    unit = {
        "unit_id": unit_id,
        "profile": profile,
        "lifecycle": "Active",
        "correspondence": correspondence,
        "source_sha": source_sha,
        "validation": _validation(),
        "limitations": [],
    }
    if profile == "gitops-production-ref":
        unit["selector"] = {
            "system": "git",
            "strategy": "exact-ref-commit-and-path",
            "production_ref": f"refs/heads/production-{unit_id}",
            "ref_commit_sha": source_sha,
            "path": f"environments/{unit_id}",
            "content_sha256": DIGEST,
        }
    else:
        unit["selector"] = {
            "system": "github-deployments",
            "strategy": "exact-deployment-id",
            "environment": "production",
            "deployment_id": 401 + len(unit_id),
            "required_status": "success",
            "artifact": {
                "reference": f"ghcr.io/example/{unit_id}@sha256:{DIGEST}",
                "sha256": DIGEST,
            },
        }
    return unit


def _identity(units: list[dict]) -> dict:
    correspondences = {unit["correspondence"] for unit in units}
    configured = (
        "Per-unit combination" if len(correspondences) > 1 else next(iter(correspondences))
    )
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
    return validate_generic_production_identity(
        record, config=config, repository=REPOSITORY
    )


def _bundle(units: list[str], *, correspondence: object | None = None) -> dict:
    observations: dict[str, object] = {
        "M-SPI-02S": {
            "evidence_id": "E-OLD-CURRENT",
            "observed_at": NOW,
            "source": "old-normalizer",
            "subject_sha": MAIN_SHA,
            "state": "unknown",
            "completeness": "unknown",
            "complete": False,
            "population_complete": False,
            "data": {"items": []},
        }
    }
    if correspondence is not None:
        observations["M-SPI-04"] = correspondence
    return {
        "schema_version": "RH-GITHUB-OBSERVATIONS-1.0",
        "observed_at": NOW,
        "repository": REPOSITORY,
        "subject_sha": MAIN_SHA,
        "units": units,
        "complete": True,
        "population_complete": True,
        "observations": observations,
    }


def _resolution(identity: dict, states: dict[str, str], components: dict[str, dict] | None = None) -> dict:
    units: list[dict] = []
    all_gaps: list[dict] = []
    for unit in identity["units"]:
        unit_id = unit["unit_id"]
        state = states[unit_id]
        unit_components = deepcopy((components or {}).get(unit_id, {}))
        gaps = (
            []
            if state == "resolved"
            else [
                {
                    "unit_id": unit_id,
                    "code": "artifact_binding_unverified" if state == "unknown" else "artifact_mismatch",
                    "component": "artifact",
                    "message": "Fixture delivery artifact evidence is incomplete or mismatched.",
                }
            ]
        )
        all_gaps.extend(gaps)
        units.append(
            {
                "unit_id": unit_id,
                "profile": unit["profile"],
                "correspondence": unit["correspondence"],
                "source_sha": unit["source_sha"],
                "state": state,
                "traceable": True if state == "resolved" else False if state == "nonconforming" else None,
                "authoritative_source_ids": [f"source:{unit_id}"] if state != "unknown" else [],
                "evidence_statement_ids": [f"sha256:{'d' * 64}"] if state != "unknown" else [],
                "components": unit_components,
                "gaps": gaps,
            }
        )
    return {
        "schema_version": RESOLUTION_SCHEMA,
        "policy_version": POLICY_VERSION,
        "repository": REPOSITORY,
        "main_sha": MAIN_SHA,
        "complete": all(state == "resolved" for state in states.values()),
        "units": units,
        "gaps": all_gaps,
        "assurance_assigned": False,
        "score_mapping_applied": False,
    }


def _metric(results: list[dict], metric_id: str, unit_id: str | None = None) -> dict:
    return next(
        result
        for result in results
        if result["metric_id"] == metric_id and result["unit_id"] == unit_id
    )


def _known_components(unit_id: str, *, intervening: str = "pass") -> dict[str, dict]:
    return {
        unit_id: {
            "source_sha_matches": "pass",
            "main_reachable": "pass",
            "intervening_checks_passed": intervening,
        }
    }


class DeliveryMetricRoundTripTests(unittest.TestCase):
    def test_resolved_nonconforming_and_unknown_drive_g02(self) -> None:
        expectations = {
            "resolved": ("measured", "Pass", "Pass", True, "E3"),
            "nonconforming": ("measured", "Fail", "Fail", False, "E3"),
            "unknown": ("unknown", None, "Unknown", None, "E0"),
        }
        for state, expected in expectations.items():
            with self.subTest(state=state):
                identity = _identity([_unit("app")])
                transformed = apply_delivery_metrics(
                    _bundle(["app"]),
                    identity,
                    _resolution(identity, {"app": state}, _known_components("app")),
                )
                self.assertIsInstance(transformed["observations"]["M-SPI-02S"], list)
                group = transformed["observations"]["M-SPI-02S"][0]
                self.assertEqual(expected[3], group["data"]["items"][0]["traceable"])
                self.assertEqual(expected[4], group["assurance"])
                results = calculate_metrics(transformed)
                current = _metric(results, "M-SPI-02S")
                self.assertEqual((expected[0], expected[1]), (current["state"], current["band"]))
                self.assertEqual(expected[2], gate_results(results)["G-02"]["status"])

    def test_current_correspondence_cannot_pass_without_ninety_days(self) -> None:
        identity = _identity([_unit("app")])
        transformed = apply_delivery_metrics(
            _bundle(["app"]),
            identity,
            _resolution(identity, {"app": "resolved"}, _known_components("app")),
        )
        group = transformed["observations"]["M-SPI-04"][0]
        self.assertTrue(group["data"]["items"][-1]["conforming"])
        self.assertFalse(group["data"]["history_complete"])
        result = _metric(calculate_metrics(transformed), "M-SPI-04")
        self.assertEqual(("unknown", None), (result["state"], result["band"]))

    def test_ninety_unit_scoped_rows_are_preserved_and_enable_pass(self) -> None:
        history = {
            "evidence_id": "E-OLD-HISTORY",
            "observed_at": NOW,
            "source": "old-normalizer",
            "subject_sha": MAIN_SHA,
            "state": "observed",
            "completeness": "complete",
            "complete": True,
            "population_complete": True,
            "data": {
                "items": [
                    {
                        "id": f"history-app-{index}",
                        "unit": "app",
                        "is_current": False,
                        "conforming": True,
                    }
                    for index in range(90)
                ],
                "history_complete": True,
                "history_complete_by_unit": {"app": True},
                "required_daily_snapshots": 90,
            },
        }
        identity = _identity([_unit("app")])
        transformed = apply_delivery_metrics(
            _bundle(["app"], correspondence=history),
            identity,
            _resolution(identity, {"app": "resolved"}, _known_components("app")),
        )
        group = transformed["observations"]["M-SPI-04"][0]
        self.assertEqual(91, len(group["data"]["items"]))
        self.assertEqual({"app": True}, group["data"]["history_complete_by_unit"])
        result = _metric(calculate_metrics(transformed), "M-SPI-04")
        self.assertEqual(("measured", "Pass"), (result["state"], result["band"]))

    def test_contract_semantics_are_explicit_and_main_scoped(self) -> None:
        cases = [
            ("Exact-Main", MAIN_SHA, "pass", True, "must equal assessed Main"),
            ("Exact-Main", OLDER_SHA, "pass", False, "must equal assessed Main"),
            ("Releasable-Main", OLDER_SHA, "pass", True, "may trail Main"),
            ("Releasable-Main", OLDER_SHA, "fail", False, "may trail Main"),
            ("Production-Ref", OLDER_SHA, "pass", True, "production-ref SHA"),
        ]
        for contract, source_sha, intervening, expected, rule_fragment in cases:
            with self.subTest(contract=contract, source_sha=source_sha, intervening=intervening):
                identity = _identity(
                    [_unit("unit", correspondence=contract, source_sha=source_sha)]
                )
                transformed = apply_delivery_metrics(
                    _bundle(["unit"]),
                    identity,
                    _resolution(
                        identity,
                        {"unit": "nonconforming"},
                        _known_components("unit", intervening=intervening),
                    ),
                )
                row = transformed["observations"]["M-SPI-04"][0]["data"]["items"][-1]
                self.assertEqual(expected, row["conforming"])
                self.assertIn(rule_fragment, row["contract_rule"])
                if contract == "Production-Ref":
                    self.assertEqual(source_sha, row["production_ref_sha"])

    def test_multi_unit_unknown_is_isolated_and_dominates_repository_aggregate(self) -> None:
        identity = _identity([_unit("known"), _unit("unknown")])
        components = {
            **_known_components("known"),
            **_known_components("unknown"),
        }
        transformed = apply_delivery_metrics(
            _bundle(["known", "unknown"]),
            identity,
            _resolution(
                identity,
                {"known": "resolved", "unknown": "unknown"},
                components,
            ),
        )
        results = calculate_metrics(transformed, include_unit_results=True)
        self.assertEqual("Pass", _metric(results, "M-SPI-02S", "known")["band"])
        self.assertEqual("unknown", _metric(results, "M-SPI-02S", "unknown")["state"])
        self.assertEqual("unknown", _metric(results, "M-SPI-02S")["state"])
        self.assertEqual("Unknown", gate_results(results)["G-02"]["status"])

    def test_inputs_are_not_mutated(self) -> None:
        identity = _identity([_unit("app")])
        bundle = _bundle(["app"])
        resolution = _resolution(
            identity, {"app": "resolved"}, _known_components("app")
        )
        before = deepcopy((bundle, identity, resolution))
        transformed = apply_delivery_metrics(bundle, identity, resolution)
        self.assertEqual(before, (bundle, identity, resolution))
        self.assertIsNot(transformed, bundle)
        self.assertNotEqual(bundle["observations"], transformed["observations"])


if __name__ == "__main__":
    unittest.main()

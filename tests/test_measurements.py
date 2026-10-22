from __future__ import annotations

import unittest

from automation.repository_health.measurements import (
    GATE_METRICS,
    METRIC_IDS,
    calculate_metric_results,
    calculate_metrics,
    gate_results,
)
from automation.repository_health.models import MetricResult


NOW = "2026-08-09T23:00:00Z"
MAIN_SHA = "a" * 40


def observation(
    data: object,
    *,
    evidence_id: str = "E-TEST",
    observed_at: str = NOW,
    complete: bool = True,
    population_complete: bool = True,
    state: str = "observed",
    unit: str | None = None,
    conflicts: list[str] | None = None,
) -> dict:
    result = {
        "evidence_id": evidence_id,
        "observed_at": observed_at,
        "source": "TEST",
        "subject_sha": MAIN_SHA,
        "state": state,
        "completeness": "complete" if complete else "partial",
        "complete": complete,
        "population_complete": population_complete,
        "data": data,
        "freshness": {"complete": True, "fresh": True},
    }
    if unit is not None:
        result["unit"] = unit
    if conflicts:
        result["conflicts"] = conflicts
    return result


def bundle(observations: dict, *, units: list[str] | None = None, schema: str = "RH-GITHUB-OBSERVATIONS-1.0") -> dict:
    result = {
        "schema_version": schema,
        "observed_at": NOW,
        "repository": "example/health",
        "subject_sha": MAIN_SHA,
        "complete": True,
        "population_complete": True,
        "observations": observations,
    }
    if units is not None:
        result["units"] = units
    return result


def metric(raw: dict, metric_id: str) -> MetricResult:
    return next(result for result in calculate_metric_results(raw) if result.metric_id == metric_id)


class MetricContractTests(unittest.TestCase):
    def test_stable_result_contains_exact_contract_fields(self) -> None:
        result = metric(bundle({"M-SPI-01": observation({"items": [{"id": "main", "valid": True}]})}), "M-SPI-01")
        encoded = result.to_dict()
        self.assertEqual("RH-METRIC-RESULT-1.0", encoded["schema_version"])
        self.assertEqual("RH-METRICS-0.1", encoded["metric_version"])
        self.assertEqual(
            {
                "schema_version",
                "metric_version",
                "metric_id",
                "repository",
                "unit_id",
                "main_sha",
                "state",
                "band",
                "value",
                "unit",
                "numerator",
                "denominator",
                "components",
                "sample_size",
                "sample_class",
                "window",
                "coverage",
                "freshness",
                "assurance",
                "evidence_ids",
                "observation_ids",
                "source_codes",
                "threshold_version",
                "carried_band_from",
                "limitations",
                "conflicts",
                "exceptions",
            },
            set(encoded),
        )

    def test_json_wrapper_emits_all_requested_metrics(self) -> None:
        results = calculate_metrics(bundle({}))
        self.assertEqual(len(METRIC_IDS), len(results))
        self.assertEqual(set(METRIC_IDS), {item["metric_id"] for item in results})

    def test_unknown_schema_fails_all_metrics_closed(self) -> None:
        results = calculate_metric_results(bundle({}, schema="RH-GITHUB-OBSERVATIONS-9.9"))
        self.assertTrue(all(item.state == "unknown" and item.band is None for item in results))


class CurrentMetricTests(unittest.TestCase):
    def test_main_validity_pass_and_fail_are_bound_to_current_metric(self) -> None:
        passing = metric(bundle({"M-SPI-01": observation({"items": [{"id": "main", "valid": True}]})}), "M-SPI-01")
        failing = metric(bundle({"M-SPI-01": observation({"items": [{"id": "main", "valid": False}]})}), "M-SPI-01")
        self.assertEqual(("measured", "Pass", 1), (passing.state, passing.band, passing.value))
        self.assertEqual(("measured", "Fail", 0), (failing.state, failing.band, failing.value))

    def test_current_output_traceability_is_logical_across_inventory(self) -> None:
        raw = bundle(
            {
                "M-SPI-02S": observation(
                    {
                        "items": [
                            {"id": "web", "traceable": True},
                            {"id": "worker", "traceable": False},
                        ]
                    }
                )
            }
        )
        result = metric(raw, "M-SPI-02S")
        self.assertEqual("Fail", result.band)
        self.assertEqual((1, 2, 50.0), (result.numerator, result.denominator, result.value))

    def test_release_identity_overwrite_forces_failure(self) -> None:
        raw = bundle(
            {
                "M-SPI-03": observation(
                    {
                        "items": [
                            {"id": "release-1", "immutable_identity": True},
                            {"id": "release-2", "immutable_identity": True, "overwritten": True},
                        ]
                    }
                )
            }
        )
        self.assertEqual("Fail", metric(raw, "M-SPI-03").band)

    def test_releasable_main_allows_main_ahead_only_with_intervening_gates(self) -> None:
        base = {
            "id": "today",
            "is_current": True,
            "contract": "Releasable-Main",
            "production_sha": "b" * 40,
            "main_sha": MAIN_SHA,
            "reachable_from_main": True,
        }
        passing = dict(base, intervening_gates_passed=True)
        failing = dict(base, intervening_gates_passed=False)
        unknown = dict(base)
        daily = [
            {"id": f"day-{index}", "conforming": True, "is_current": False}
            for index in range(90)
        ]
        self.assertEqual(
            "Pass",
            metric(
                bundle(
                    {
                        "M-SPI-04": observation(
                            {
                                "items": [*daily, passing],
                                "history_complete": True,
                                "required_daily_snapshots": 90,
                            }
                        )
                    }
                ),
                "M-SPI-04",
            ).band,
        )
        self.assertEqual("Fail", metric(bundle({"M-SPI-04": observation({"items": [failing]})}), "M-SPI-04").band)
        self.assertEqual("unknown", metric(bundle({"M-SPI-04": observation({"items": [passing]})}), "M-SPI-04").state)
        self.assertEqual("unknown", metric(bundle({"M-SPI-04": observation({"items": [unknown]})}), "M-SPI-04").state)

    def test_audited_change_and_current_enforcement_both_required(self) -> None:
        raw = bundle(
            {
                "M-CGD-01": observation(
                    {
                        "current_enforcement": True,
                        "items": [
                            {"id": "c1", "complete": True},
                            {"id": "c2", "complete": False},
                        ],
                    }
                )
            }
        )
        result = metric(raw, "M-CGD-01")
        self.assertEqual("Fail", result.band)
        self.assertEqual((1, 2), (result.numerator, result.denominator))

    def test_critical_ref_requires_all_five_assertions(self) -> None:
        assertions = {
            "restricted_update": True,
            "deletion_protection": True,
            "force_push_protection": True,
            "required_acceptance_checks": True,
            "controlled_audited_bypass": True,
        }
        passing = metric(bundle({"M-CGD-02": observation({"items": [{"ref": "main", "assertions": assertions}]})}), "M-CGD-02")
        failing_assertions = dict(assertions, deletion_protection=False)
        failing = metric(bundle({"M-CGD-02": observation({"items": [{"ref": "main", "assertions": failing_assertions}]})}), "M-CGD-02")
        self.assertEqual("Pass", passing.band)
        self.assertEqual("Fail", failing.band)


class HistoryMetricTests(unittest.TestCase):
    def test_offset_free_observation_timestamp_is_unknown(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": observation(
                    {"items": [{"id": "main", "valid": True}]},
                    observed_at="2026-08-09T20:00:00",
                )
            }
        )
        result = metric(raw, "M-SPI-01")
        self.assertEqual("unknown", result.state)

    def test_future_observation_timestamp_is_unknown(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": observation(
                    {"items": [{"id": "main", "valid": True}]},
                    observed_at="2026-08-10T23:00:00Z",
                )
            }
        )
        result = metric(raw, "M-SPI-01")
        self.assertEqual("unknown", result.state)

    def test_main_invalid_duration_uses_defined_thresholds(self) -> None:
        raw = bundle(
            {
                "M-SPI-01T": observation(
                    {
                        "invalid_minutes": 300,
                        "observable_minutes": 10_000,
                        "items": [{"id": "outage", "duration_minutes": 300}],
                    }
                )
            }
        )
        result = metric(raw, "M-SPI-01T")
        self.assertEqual(("Concern", 3.0), (result.band, result.value))
        self.assertEqual(300.0, result.components["p95_interval_minutes"])

    def test_no_main_events_carries_current_band(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": observation({"items": [{"id": "main", "valid": True}]}),
                "M-SPI-01T": observation({"items": [], "no_events": True, "observable_minutes": 129_600}),
            }
        )
        result = metric(raw, "M-SPI-01T")
        self.assertEqual(("no_events", "Pass", "M-SPI-01"), (result.state, result.band, result.carried_band_from))

    def test_no_release_events_carries_current_traceability(self) -> None:
        raw = bundle(
            {
                "M-SPI-02S": observation({"items": [{"id": "current", "traceable": True}]}),
                "M-SPI-02": observation({"items": [], "no_events": True}),
            }
        )
        result = metric(raw, "M-SPI-02")
        self.assertEqual(("no_events", "Pass", "M-SPI-02S"), (result.state, result.band, result.carried_band_from))

    def test_build_replay_rate_and_low_sample(self) -> None:
        replays = [
            {
                "id": f"run-{index}",
                "main_sha": str(index) * 40,
                "clean_checkout": True,
                "non_interactive": True,
                "declared_inputs": True,
                "successful": index != 0,
                "completed_at": f"2026-08-0{index + 1}T00:00:00Z",
            }
            for index in range(4)
        ]
        result = metric(bundle({"M-BTC-01": observation({"replays": replays})}), "M-BTC-01")
        self.assertEqual(("Fail", 75.0, "Low Sample"), (result.band, result.value, result.sample_class))

    def test_per_change_ci_and_required_categories(self) -> None:
        ci = metric(
            bundle({"M-BTC-02": observation({"changes": [{"id": "c1", "all_applicable_workflows_triggered": True}]})}),
            "M-BTC-02",
        )
        category_rows = [{"id": f"pair-{i}", "successful": True} for i in range(19)]
        category_rows.append({"id": "critical", "successful": False, "critical": True})
        categories = metric(bundle({"M-BTC-03": observation({"category_pairs": category_rows})}), "M-BTC-03")
        self.assertEqual("Pass", ci.band)
        self.assertEqual((95.0, "Fail"), (categories.value, categories.band))

    def test_feedback_latency_uses_nearest_rank_p95(self) -> None:
        rows = [{"id": f"r{i}", "latency_minutes": value} for i, value in enumerate([5, 10, 15, 20, 40])]
        result = metric(bundle({"M-BTC-04": observation({"latencies": rows, "slo_minutes": 30})}), "M-BTC-04")
        self.assertEqual((40.0, "Concern", 15.0), (result.value, result.band, result.components["median_minutes"]))

    def test_zero_reruns_requires_complete_retry_capture(self) -> None:
        passing = metric(bundle({"M-BTC-05": observation({"rerun_groups": [], "retry_capture_enabled": True})}), "M-BTC-05")
        unknown = metric(bundle({"M-BTC-05": observation({"rerun_groups": []})}), "M-BTC-05")
        self.assertEqual(("measured", "Pass", 0.0), (passing.state, passing.band, passing.value))
        self.assertEqual("unknown", unknown.state)

    def test_no_change_enforcement_requires_tested_boundary(self) -> None:
        passing = metric(bundle({"M-CGD-04": observation({"changes": [], "tested_enforcement": True})}), "M-CGD-04")
        unknown = metric(bundle({"M-CGD-04": observation({"changes": []})}), "M-CGD-04")
        self.assertEqual("Pass", passing.band)
        self.assertEqual("unknown", unknown.state)


class FailClosedTests(unittest.TestCase):
    def test_partial_population_cannot_pass(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": observation(
                    {"items": [{"id": "main", "valid": True}]},
                    complete=False,
                    population_complete=False,
                )
            }
        )
        result = metric(raw, "M-SPI-01")
        self.assertEqual("unknown", result.state)
        self.assertFalse(result.coverage["complete"])

    def test_stale_observation_cannot_pass(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": observation(
                    {"items": [{"id": "main", "valid": True}]},
                    observed_at="2026-08-07T22:00:00Z",
                )
            }
        )
        raw["observations"]["M-SPI-01"].pop("freshness")
        result = metric(raw, "M-SPI-01")
        self.assertEqual("unknown", result.state)
        self.assertFalse(result.freshness["fresh"])

    def test_conflicting_observations_are_unknown(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": [
                    observation({"items": [{"id": "main", "valid": True}]}, evidence_id="E-ONE"),
                    observation({"items": [{"id": "main", "valid": False}]}, evidence_id="E-TWO"),
                ]
            }
        )
        result = metric(raw, "M-SPI-01")
        self.assertEqual("unknown", result.state)
        self.assertTrue(result.conflicts)

    def test_any_unknown_unit_makes_repository_unknown(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": [
                    observation({"items": [{"id": "a-main", "valid": True, "unit": "a"}]}, unit="a"),
                    observation(
                        {"items": [{"id": "b-main", "valid": True, "unit": "b"}]},
                        unit="b",
                        complete=False,
                        population_complete=False,
                    ),
                ]
            },
            units=["a", "b"],
        )
        result = metric(raw, "M-SPI-01")
        self.assertIsNone(result.unit_id)
        self.assertEqual("unknown", result.state)
        self.assertIn("At least one applicable unit is Unknown.", result.limitations)

    def test_unscoped_rows_cannot_prove_multiple_units(self) -> None:
        raw = bundle(
            {
                "M-SPI-03": observation(
                    {
                        "items": [
                            {
                                "id": "release-for-unknown-unit",
                                "immutable_identity": True,
                            }
                        ]
                    }
                )
            },
            units=["application", "worker"],
        )
        results = calculate_metric_results(raw, include_unit_results=True)
        repository = next(item for item in results if item.metric_id == "M-SPI-03" and item.unit_id is None)
        per_unit = [item for item in results if item.metric_id == "M-SPI-03" and item.unit_id is not None]
        self.assertEqual("unknown", repository.state)
        self.assertEqual({"application", "worker"}, {item.unit_id for item in per_unit})
        self.assertTrue(all(item.state == "unknown" for item in per_unit))

    def test_empty_inventory_does_not_fabricate_n_a(self) -> None:
        raw = bundle({"M-SPI-02S": observation({"items": []})})
        self.assertEqual("unknown", metric(raw, "M-SPI-02S").state)

    def test_evidence_backed_n_a_is_retained_without_band(self) -> None:
        raw = bundle(
            {
                "M-SPI-02S": observation(
                    {
                        "items": [],
                        "state": "n_a",
                        "applicable": False,
                        "n_a_evidence": True,
                        "n_a_reason": "Complete current inventory proves no output or supported consumer.",
                    }
                )
            }
        )
        result = metric(raw, "M-SPI-02S")
        self.assertEqual("n_a", result.state)
        self.assertIsNone(result.band)

    def test_only_current_foundational_metrics_map_to_gates(self) -> None:
        raw = bundle(
            {
                "M-SPI-01": observation({"items": [{"id": "main", "valid": True}]}),
                "M-SPI-02S": observation({"items": [{"id": "out", "traceable": True}]}),
                "M-CGD-01": observation({"items": [{"id": "c1", "complete": True}], "current_enforcement": True}),
                "M-CGD-02": observation(
                    {
                        "items": [
                            {
                                "ref": "main",
                                "assertions": {
                                    "restricted_update": True,
                                    "deletion_protection": True,
                                    "force_push_protection": True,
                                    "required_acceptance_checks": True,
                                    "controlled_audited_bypass": True,
                                },
                            }
                        ]
                    }
                ),
            }
        )
        gates = gate_results(calculate_metric_results(raw))
        self.assertEqual(GATE_METRICS, {gate: item["metric_id"] for gate, item in gates.items()})
        self.assertTrue(all(item["status"] == "Pass" for item in gates.values()))


if __name__ == "__main__":
    unittest.main()

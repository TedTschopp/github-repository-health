from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess
import tempfile
import unittest
from urllib.error import HTTPError

from automation.repository_health.catalog import parse_catalog
from automation.repository_health.collectors import GitHubClient, collect_github, github_check_state
from automation.repository_health.configuration import DEFAULT_CONFIG, load_config
from automation.repository_health.engine import _evidence_records, assess_repository
from automation.repository_health.evaluator import (
    applicability,
    automatic_control_result,
    evaluate_controls,
    resolved_repository_facts,
    summarize,
)


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "control-catalog.md"


def result(control_id: str, dimension: str, conformance: str = "Met", assurance: str = "E3", gate: str | None = None) -> dict:
    points = {"Met": 100.0, "Partially met": 50.0, "Unmet": 0.0, "Unknown": 0.0, "N/A": None}[conformance]
    return {
        "control_id": control_id,
        "title": control_id,
        "dimension": dimension,
        "gate": gate,
        "applicable": conformance != "N/A",
        "conformance": conformance,
        "points": points,
        "assurance": assurance,
        "minimum_assurance": "E3",
        "rationale": "test",
    }


def all_dimension_results() -> list[dict]:
    return [
        result("SPI-01", "SPI", gate="G-01"),
        result("SPI-02", "SPI", gate="G-02"),
        result("BTC-01", "BTC"),
        result("CGD-01", "CGD", gate="G-03"),
        result("CGD-02", "CGD", gate="G-04"),
        result("SSC-01", "SSC"),
        result("OWM-01", "OWM"),
        result("DCR-01", "DCR"),
        result("RRO-01", "RRO"),
        result("RLP-01", "RLP"),
    ]


def metric_result(
    metric_id: str,
    *,
    state: str = "measured",
    band: str | None = "Pass",
    assurance: str = "E3",
    value: float | None = 100.0,
    limitations: list[str] | None = None,
) -> dict:
    return {
        "schema_version": "RH-METRIC-RESULT-1.0",
        "metric_version": "RH-METRICS-0.1",
        "metric_id": metric_id,
        "repository": "example/repo",
        "unit_id": None,
        "main_sha": "a" * 40,
        "state": state,
        "band": band,
        "value": value,
        "unit": "percent" if value is not None else None,
        "assurance": assurance,
        "evidence_ids": [f"E-{metric_id}"],
        "limitations": limitations or [],
        "conflicts": [],
    }


class CatalogTests(unittest.TestCase):
    def test_catalog_parses_all_controls_and_gates(self) -> None:
        catalog = parse_catalog(CATALOG)
        self.assertEqual(35, len(catalog.controls))
        self.assertEqual("0.1.0-draft", catalog.standard_version)
        self.assertEqual({"G-01", "G-02", "G-03", "G-04"}, {item.gate for item in catalog.controls if item.gate})


class ScoringTests(unittest.TestCase):
    def test_equal_dimension_scoring(self) -> None:
        controls = all_dimension_results()
        controls[-1] = result("RLP-01", "RLP", "Partially met", "E3")
        dimensions, gates, score, assurance = summarize(controls)
        self.assertEqual(50.0, dimensions["RLP"]["score"])
        self.assertEqual(100.0, dimensions["RLP"]["applicability_coverage"])
        self.assertEqual(100.0, dimensions["RLP"]["evidence_coverage"])
        self.assertEqual(93.8, score["raw"])
        self.assertEqual("A", score["effective_grade"])
        self.assertFalse(score["cap_active"])
        self.assertEqual("High", assurance["label"])
        self.assertTrue(all(item["status"] == "Pass" for item in gates.values()))

    def test_unknown_gate_caps_high_raw_score(self) -> None:
        controls = all_dimension_results()
        controls[0] = result("SPI-01", "SPI", "Unknown", "E0", "G-01")
        _, gates, score, _ = summarize(controls)
        self.assertEqual("Unknown", gates["G-01"]["status"])
        self.assertGreater(score["raw"], 69.0)
        self.assertEqual(69.0, score["effective"])
        self.assertEqual("D", score["effective_grade"])
        self.assertTrue(score["cap_active"])
        self.assertTrue(score["numeric_cap_changed_score"])

    def test_gate_cap_remains_active_when_raw_score_is_already_f(self) -> None:
        controls = all_dimension_results()
        for index, item in enumerate(controls):
            controls[index] = result(item["control_id"], item["dimension"], "Unmet", "E3", item["gate"])
        _, _, score, _ = summarize(controls)
        self.assertEqual(0.0, score["effective"])
        self.assertEqual("F", score["effective_grade"])
        self.assertTrue(score["cap_active"])
        self.assertTrue(score["cap_applied"])
        self.assertFalse(score["numeric_cap_changed_score"])

    def test_explicit_gate_pass_below_assurance_floor_fails_closed(self) -> None:
        controls = all_dimension_results()
        controls[0]["conformance"] = "Partially met"
        controls[0]["points"] = 50.0
        controls[0]["assurance"] = "E2"
        controls[0]["gate_status"] = "Pass"
        _, gates, score, _ = summarize(controls)
        self.assertEqual("Unknown", gates["G-01"]["status"])
        self.assertTrue(score["cap_active"])


class ApplicabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = deepcopy(DEFAULT_CONFIG["repository"])
        self.facts.update(
            {
                "type": "Deployable application",
                "lifecycle": "Active",
                "risk_tier": "Baseline",
                "publishes_artifacts": False,
                "has_current_output": False,
                "has_dependencies": False,
                "has_automation": False,
                "has_proposed_change_validation": False,
                "multi_contributor": False,
                "has_critical_paths": False,
                "has_produced_artifacts": False,
                "automated_deployment": False,
                "operated_service": False,
                "portfolio_managed": False,
                "has_work_refs": False,
            }
        )

    def test_elevated_tier_makes_release_controls_applicable(self) -> None:
        self.facts["risk_tier"] = "Elevated"
        self.assertTrue(applicability("SPI-03", self.facts)[0])
        self.assertTrue(applicability("SPI-04", self.facts)[0])
        self.assertTrue(applicability("RRO-03", self.facts)[0])

    def test_declared_false_does_not_auto_approve_na(self) -> None:
        applies, reason = applicability("SPI-02", self.facts)
        self.assertTrue(applies)
        self.assertIn("N/A requires an approved", reason)

    def test_active_repository_is_explicitly_na_for_retirement_control(self) -> None:
        applies, reason = applicability("RLP-03", self.facts)
        self.assertFalse(applies)
        self.assertIn("explicit catalog lifecycle", reason)


class UnknownAndApiGapTests(unittest.TestCase):
    def test_neutral_or_skipped_checks_are_not_success(self) -> None:
        github = {
            "data": {
                "check_runs": {
                    "check_runs": [
                        {"name": "build", "status": "completed", "conclusion": "neutral"},
                        {"name": "test", "status": "completed", "conclusion": "skipped"},
                    ]
                }
            }
        }
        state, _ = github_check_state(github, ["build", "test"])
        self.assertEqual("unknown", state)

    def test_unlisted_health_action_cannot_satisfy_main_gate(self) -> None:
        github = {
            "data": {
                "check_runs": {
                    "check_runs": [
                        {"name": "repository-health", "status": "completed", "conclusion": "success"},
                    ]
                }
            }
        }
        state, names = github_check_state(github, ["authoritative-build"])
        self.assertEqual("unknown", state)
        self.assertEqual([], names)

    def test_current_main_can_pass_gate_without_inflating_trend_control(self) -> None:
        control = next(item for item in parse_catalog(CATALOG).controls if item.control_id == "SPI-01")
        github = {
            "data": {
                "check_runs": {
                    "check_runs": [
                        {"name": "authoritative-build", "status": "completed", "conclusion": "success"},
                    ]
                }
            }
        }
        observed = automatic_control_result(
            control,
            {"documents": {}, "workflows": []},
            github,
            {"authoritative_checks": ["authoritative-build"]},
        )
        self.assertEqual("Pass", observed["gate_status"])
        self.assertEqual("Unknown", observed["conformance"])
        self.assertEqual("E3", observed["assurance"])

    def test_versioned_current_metric_can_pass_gate_while_trend_remains_unknown(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["repository"].update(
            {"type": "Deployable application", "owner": "team", "risk_tier": "Baseline"}
        )
        metrics = [
            metric_result("M-SPI-01"),
            metric_result(
                "M-SPI-01T",
                state="unknown",
                band=None,
                assurance="E0",
                value=None,
                limitations=["The 90-day Main-validity population is incomplete."],
            ),
        ]
        controls = evaluate_controls(
            catalog,
            config,
            {
                "documents": {},
                "workflows": [],
                "dependency_files": [],
                "lock_files": [],
                "working_tree_clean": True,
                "head_is_main": True,
            },
            {"data": {}},
            metrics,
        )
        spi01 = next(item for item in controls if item["control_id"] == "SPI-01")
        self.assertEqual("Unknown", spi01["conformance"])
        self.assertEqual("Pass", spi01["gate_status"])
        self.assertIn("90-day", spi01["rationale"])
        self.assertEqual(2, len(spi01["measurement_results"]))

    def test_missing_declared_metric_forces_control_unknown_without_hiding_current_gate(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["repository"].update(
            {"type": "Deployable application", "owner": "team", "risk_tier": "Baseline"}
        )
        controls = evaluate_controls(
            catalog,
            config,
            {
                "documents": {},
                "workflows": [],
                "dependency_files": [],
                "lock_files": [],
                "working_tree_clean": True,
                "head_is_main": True,
            },
            {"data": {}},
            [metric_result("M-SPI-01")],
        )
        spi01 = next(item for item in controls if item["control_id"] == "SPI-01")
        self.assertEqual("Unknown", spi01["conformance"])
        self.assertEqual("Pass", spi01["gate_status"])
        self.assertEqual(
            {"M-SPI-01", "M-SPI-01T"},
            {item["metric_id"] for item in spi01["measurement_results"]},
        )
        missing = next(item for item in spi01["measurement_results"] if item["metric_id"] == "M-SPI-01T")
        self.assertEqual("unknown", missing["state"])

    def test_versioned_gate_metric_requires_e3_to_pass(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["repository"].update(
            {"type": "Deployable application", "owner": "team", "risk_tier": "Baseline"}
        )
        controls = evaluate_controls(
            catalog,
            config,
            {
                "documents": {},
                "workflows": [],
                "dependency_files": [],
                "lock_files": [],
                "working_tree_clean": True,
                "head_is_main": True,
            },
            {"data": {}},
            [metric_result("M-CGD-01", assurance="E2")],
        )
        cgd01 = next(item for item in controls if item["control_id"] == "CGD-01")
        self.assertEqual("Partially met", cgd01["conformance"])
        self.assertEqual("Unknown", cgd01["gate_status"])

    def test_versioned_failed_metric_drives_control_and_gate_failure(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["repository"].update(
            {"type": "Deployable application", "owner": "team", "risk_tier": "Baseline"}
        )
        controls = evaluate_controls(
            catalog,
            config,
            {
                "documents": {},
                "workflows": [],
                "dependency_files": [],
                "lock_files": [],
                "working_tree_clean": True,
                "head_is_main": True,
            },
            {"data": {}},
            [metric_result("M-CGD-02", band="Fail", value=0.0)],
        )
        cgd02 = next(item for item in controls if item["control_id"] == "CGD-02")
        self.assertEqual("Unmet", cgd02["conformance"])
        self.assertEqual("Fail", cgd02["gate_status"])

    def test_http_403_becomes_explicit_evidence_gap(self) -> None:
        def forbidden(request, timeout=0):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, None)

        github = collect_github("example/repo", "main", "abc123", GitHubClient(token="x", transport=forbidden))
        self.assertFalse(github["available"])
        self.assertGreaterEqual(len(github["gaps"]), 8)
        self.assertTrue(all("HTTP 403" in gap for gap in github["gaps"]))

    def test_met_override_below_assurance_floor_is_not_met(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["repository"].update({"type": "Deployable application", "owner": "team", "risk_tier": "Baseline"})
        config["controls"] = {
            "SPI-01": {
                "conformance": "Met",
                "assurance": "E1",
                "rationale": "Only declared.",
                "evidence_ids": ["E-DECLARED"],
            }
        }
        local = {
            "dependency_files": [],
            "workflows": [],
            "contributor_count": 1,
            "branch_count": 1,
            "documents": {},
            "branches": [],
        }
        github = {"available": False, "data": {}, "gaps": []}
        controls = evaluate_controls(catalog, config, local, github)
        spi01 = next(item for item in controls if item["control_id"] == "SPI-01")
        self.assertEqual("Partially met", spi01["conformance"])
        self.assertEqual(50.0, spi01["points"])

    def test_dirty_working_tree_file_evidence_is_only_declared_state(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["_config_path"] = str(CATALOG)
        local = {
            "root": str(ROOT),
            "dependency_files": [],
            "workflows": [],
            "contributor_count": 1,
            "branch_count": 1,
            "documents": {},
            "branches": [],
            "working_tree_clean": False,
            "head_is_main": True,
            "is_git_repository": True,
        }
        github = {"available": False, "data": {}, "gaps": []}
        controls = evaluate_controls(catalog, config, local, github)
        dcr01 = next(item for item in controls if item["control_id"] == "DCR-01")
        self.assertEqual("Unknown", dcr01["conformance"])
        self.assertEqual("E1", dcr01["assurance"])
        records = _evidence_records(config, local, github, "2026-08-09T20:00:00+00:00")
        local_docs = next(item for item in records if item["evidence_id"] == "E-LOCAL-DOCS")
        self.assertEqual("E1", local_docs["assurance"])
        self.assertIn("not proven", local_docs["notes"])

    def test_github_configuration_and_event_evidence_use_distinct_assurance(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["_config_path"] = str(ROOT / ".github" / "repository-health.toml")
        local = {
            "root": str(ROOT),
            "is_git_repository": True,
            "working_tree_clean": True,
            "head_is_main": True,
        }

        def group(evidence_id: str, data: dict) -> dict:
            return {
                "evidence_id": evidence_id,
                "source": "GitHub REST",
                "observed_at": "2026-08-09T20:00:00+00:00",
                "complete": True,
                "population_complete": True,
                "data": data,
                "gaps": [],
                "request": {"endpoints": []},
            }

        bundle = {
            "observed_at": "2026-08-09T20:00:00+00:00",
            "observations": {
                "repository_identity": group("E-GH-IDENTITY", {"default_branch": "main"}),
                "rules": group("E-GH-RULES", {"rulesets": [{"id": 1}]}),
                "check_runs": group("E-GH-CHECKS", {"check_runs": [{"id": 1}]}),
            },
        }
        records = _evidence_records(
            config,
            local,
            {"data": {}},
            "2026-08-09T20:00:00+00:00",
            observation_bundle=bundle,
        )
        by_id = {item["evidence_id"]: item for item in records}
        self.assertEqual("E2", by_id["E-GH-IDENTITY"]["assurance"])
        self.assertEqual("E2", by_id["E-GH-RULES"]["assurance"])
        self.assertEqual("E3", by_id["E-GH-CHECKS"]["assurance"])

    def test_bounded_history_window_does_not_claim_full_chain_validation(self) -> None:
        config = deepcopy(DEFAULT_CONFIG)
        config["_config_path"] = str(ROOT / ".github" / "repository-health.toml")
        local = {
            "root": str(ROOT),
            "is_git_repository": True,
            "working_tree_clean": True,
            "head_is_main": True,
        }
        durable_history = {
            "evidence_id": "E-GH-DURABLE-HISTORY",
            "state": "observed",
            "complete": True,
            "branch": "repository-health-evidence",
            "observed_at": "2026-08-09T20:00:00+00:00",
            "validation_scope": "bounded_newest_segment",
            "segment_complete": True,
            "window_complete": True,
            "full_chain_complete": False,
            "opaque_predecessor_sha256": "f" * 64,
            "snapshots": [
                {"generated_at": "2025-08-09T20:00:00+00:00"},
                {"generated_at": "2026-08-09T20:00:00+00:00"},
            ],
            "gaps": [],
        }

        records = _evidence_records(
            config,
            local,
            {"data": {}},
            "2026-08-09T20:00:00+00:00",
            durable_history=durable_history,
        )
        history = next(
            item for item in records if item["evidence_id"] == "E-GH-DURABLE-HISTORY"
        )

        self.assertIn("bounded newest segment", history["population_coverage"])
        self.assertIn("opaque anchor", history["population_coverage"])
        self.assertNotIn("from genesis", history["population_coverage"])

    def test_control_override_requires_evidence_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "health.toml"
            config_path.write_text(
                '[controls."SPI-01"]\nconformance="Met"\nassurance="E3"\nrationale="Claim only"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "evidence_ids"):
                load_config(config_path)

    def test_na_requires_evidence_stronger_than_e0(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "health.toml"
            config_path.write_text(
                '[controls."SPI-02"]\n'
                'conformance="N/A"\n'
                'assurance="E0"\n'
                'rationale="No current output."\n'
                'evidence_ids=["E-NO-OUTPUT"]\n'
                'n_a_approved_by="Architecture"\n'
                'n_a_approved_at="2026-08-09"\n'
                'n_a_review_date="2026-11-07"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "E1 or stronger"):
                load_config(config_path)

    def test_whole_control_na_cannot_remove_never_na_gate(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["repository"].update(
            {
                "type": "Deployable application",
                "lifecycle": "Active",
                "risk_tier": "Baseline",
            }
        )
        config["controls"] = {
            "SPI-01": {
                "conformance": "N/A",
                "assurance": "E2",
                "rationale": "Attempted whole-control exclusion.",
                "evidence_ids": ["E-INVALID-NA"],
                "n_a_approved_by": "Architecture",
                "n_a_approved_at": "2026-08-09",
                "n_a_review_date": "2026-11-07",
            }
        }
        with self.assertRaisesRegex(ValueError, "does not permit a whole-control N/A"):
            evaluate_controls(
                catalog,
                config,
                {
                    "documents": {},
                    "workflows": [],
                    "dependency_files": [],
                    "lock_files": [],
                    "working_tree_clean": True,
                    "head_is_main": True,
                },
                {"data": {}},
            )

    def test_evidence_backed_catalog_na_remains_available(self) -> None:
        catalog = parse_catalog(CATALOG)
        config = deepcopy(DEFAULT_CONFIG)
        config["repository"].update(
            {
                "type": "Documentation/content",
                "lifecycle": "Active",
                "risk_tier": "Baseline",
                "has_current_output": False,
            }
        )
        config["controls"] = {
            "SPI-02": {
                "conformance": "N/A",
                "assurance": "E2",
                "rationale": "Current portfolio evidence confirms there is no deployed or published output.",
                "evidence_ids": ["E-NO-CURRENT-OUTPUT"],
                "n_a_approved_by": "Architecture",
                "n_a_approved_at": "2026-08-09",
                "n_a_review_date": "2026-11-07",
            }
        }
        controls = evaluate_controls(
            catalog,
            config,
            {
                "documents": {},
                "workflows": [],
                "dependency_files": [],
                "lock_files": [],
                "working_tree_clean": True,
                "head_is_main": True,
            },
            {"data": {}},
        )
        result = next(item for item in controls if item["control_id"] == "SPI-02")
        self.assertFalse(result["applicable"])
        self.assertEqual("N/A", result["conformance"])

    def test_standard_version_mismatch_fails_before_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "health.toml"
            config_path.write_text('[standard]\nversion="9.9"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not match catalog"):
                assess_repository(repository=directory, catalog_path=CATALOG, config_path=config_path, github_token="")

    def test_assessment_emits_versioned_repository_and_unit_metrics(self) -> None:
        assessment = assess_repository(
            repository=ROOT,
            catalog_path=CATALOG,
            config_path=ROOT / ".github" / "repository-health.toml",
            github_token="",
            now=None,
        )
        repository_metrics = [
            item for item in assessment["measurements"] if item["unit_id"] is None
        ]
        unit_metrics = [
            item
            for item in assessment["measurements"]
            if item["unit_id"] == "github-repository-health"
        ]
        self.assertEqual(14, len(repository_metrics))
        self.assertEqual(14, len(unit_metrics))
        self.assertTrue(
            all(item["schema_version"] == "RH-METRIC-RESULT-1.0" for item in assessment["measurements"])
        )
        self.assertEqual("0.2.0", assessment["automation"]["engine_version"])
        self.assertGreater(
            len(assessment["facts"]["local"]["workflow_dependencies"]["observations"]),
            0,
        )

    def test_dirty_risk_tier_and_control_override_cannot_change_exact_main_score(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "-C", str(root), "init", "-b", "main"], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(root), "config", "user.name", "Health Test"], check=True)
            subprocess.run(["git", "-C", str(root), "config", "user.email", "health@example.invalid"], check=True)
            config_path = root / ".github" / "repository-health.toml"
            config_path.parent.mkdir(parents=True)
            committed_config = (ROOT / ".github" / "repository-health.toml").read_bytes()
            config_path.write_bytes(committed_config)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "fixture"], check=True, capture_output=True)

            dirty = committed_config.decode("utf-8").replace(
                'risk_tier = "Baseline"',
                'risk_tier = "Critical"',
                1,
            )
            dirty += (
                '\n[controls."SPI-02"]\n'
                'conformance = "N/A"\n'
                'assurance = "E2"\n'
                'rationale = "Dirty override must not be used."\n'
                'evidence_ids = ["E-DIRTY"]\n'
                'n_a_approved_by = "Uncommitted"\n'
                'n_a_approved_at = "2026-08-09"\n'
                'n_a_review_date = "2026-11-07"\n'
            )
            config_path.write_text(dirty, encoding="utf-8")

            assessment = assess_repository(
                repository=root,
                catalog_path=CATALOG,
                config_path=config_path,
                github_token="",
            )

            self.assertEqual("Baseline", assessment["classification"]["risk_tier"])
            self.assertFalse(any(item.get("evidence_ids") == ["E-DIRTY"] for item in assessment["controls"]))
            self.assertEqual(
                hashlib.sha256(committed_config).hexdigest(),
                assessment["automation"]["config_sha256"],
            )

    def test_available_dora_requires_all_five_metrics_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "health.toml"
            config_path.write_text('[dora]\navailable=true\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Available DORA input requires"):
                load_config(config_path)

    def test_unknown_repository_config_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "health.toml"
            config_path.write_text('[repository]\nrisk_tier="Baseline"\nrisk_teir="Critical"\n', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Unknown repository configuration keys"):
                load_config(config_path)

    def test_unknown_standard_key_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "health.toml"
            config_path.write_text(
                '[standard]\nversion="0.1.0-draft"\nversions="typo"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "standard must contain only"):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()

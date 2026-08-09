"""Isolated regression tests for assessment and leadership report rendering."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from automation.repository_health.reporting import (
    ACTION_MAP_PATH,
    build_leadership_summary,
    load_action_map,
    render_health_assessment,
    render_leadership_summary,
    write_reports,
)


def assessment_fixture() -> dict:
    """Return a complete schema-1.0 assessment with mixed, auditable results."""

    action_map = load_action_map()
    dimensions = {
        code: {
            "name": name,
            "score": 62.5 if code in {"SPI", "CGD"} else 75.0,
            "applicable_controls": sum(1 for control_id in action_map if control_id.startswith(code)),
            "total_controls": sum(1 for control_id in action_map if control_id.startswith(code)),
            "coverage": 100.0,
        }
        for code, name in {
            "SPI": "Source-to-production integrity",
            "BTC": "Build, test, and CI health",
            "CGD": "Change governance and branch discipline",
            "SSC": "Security and software-supply-chain health",
            "OWM": "Ownership and maintainability",
            "DCR": "Documentation and contributor readiness",
            "RRO": "Release, rollback, and operational readiness",
            "RLP": "Repository lifecycle and portfolio hygiene",
        }.items()
    }
    gates_by_control = {
        "SPI-01": "G-01",
        "SPI-02": "G-02",
        "CGD-01": "G-03",
        "CGD-02": "G-04",
    }
    gap_states = {
        # SPI-01's trend is Unknown while its authoritative current-state gate
        # passes. This guards against treating control and gate status as equal.
        "SPI-01": ("Unknown", "E0", "Current Main passed, but broken-duration history was not supplied."),
        "SPI-02": ("Unknown", "E0", "No current production identity was available."),
        "CGD-01": ("Unmet", "E2", "One accepted Main change lacked a complete audit chain."),
        "CGD-03": ("Partially met", "E2", "Independent final-version review was not complete."),
        "SSC-01": ("Unmet", "E2", "Credential prevention was not enabled."),
        "SSC-03": ("Partially met", "E2", "Two high-risk component findings are overdue."),
        "OWM-01": ("Unmet", "E1", "No acknowledged backup owner was recorded."),
        "RRO-02": ("Unknown", "E0", "No recent recovery exercise evidence was supplied."),
        "DCR-02": ("Partially met", "E1", "The urgent-change path is not documented."),
        "RLP-02": ("Partially met", "E2", "Several old source lines have no owner or expiry."),
    }
    controls = []
    for control_id, mapping in action_map.items():
        conformance, assurance, rationale = gap_states.get(
            control_id, ("Met", "E3", "The supplied evidence met the control threshold.")
        )
        controls.append(
            {
                "control_id": control_id,
                "title": mapping["title"],
                "dimension": control_id.split("-", 1)[0],
                "gate": gates_by_control.get(control_id),
                "applicable": True,
                "applicability_reason": "Applicable under the repository classification.",
                "conformance": conformance,
                "points": 100 if conformance == "Met" else 50 if conformance == "Partially met" else 0,
                "assurance": assurance,
                "minimum_assurance": "E3",
                "evidence_ids": [f"E-{control_id}"],
                "rationale": rationale,
                "remediation": mapping["action"],
                "source": "mixed",
            }
        )
    return {
        "schema_version": "1.0",
        "standard_version": "0.1.0-draft",
        "standard_status": "provisional-draft-not-calibrated",
        "assessment_id": "RHA-TEST-001",
        "generated_at": "2026-08-09T20:00:00+00:00",
        "repository": {
            "identity": "example/payments",
            "path": "/workspace/payments",
            "default_branch": "main",
            "main_sha": "a" * 40,
            "assessed_checkout_sha": "a" * 40,
            "deployable_units": ["payments-api"],
        },
        "classification": {
            "type": "Deployable application",
            "lifecycle": "Active",
            "risk_tier": "Elevated",
            "owner": "Payments product owner",
            "declared_methodology": "Trunk-based",
            "observed_methodology": "Trunk-based",
            "methodology_confidence": "High",
            "methodology_assurance": "E2",
            "contradictions": [],
        },
        "controls": controls,
        "dimensions": dimensions,
        "gates": {
            "G-01": {
                "control_id": "SPI-01",
                "status": "Pass",
                "assurance": "E3",
                "rationale": "The exact Main revision passed every authoritative check.",
            },
            "G-02": {
                "control_id": "SPI-02",
                "status": "Unknown",
                "assurance": "E0",
                "rationale": "The current production identity is not available.",
            },
            "G-03": {
                "control_id": "CGD-01",
                "status": "Fail",
                "assurance": "E2",
                "rationale": "An accepted change lacked its required audit chain.",
            },
            "G-04": {
                "control_id": "CGD-02",
                "status": "Pass",
                "assurance": "E3",
                "rationale": "Production-critical references are protected.",
            },
        },
        "score": {
            "raw": 78.4,
            "effective": 69.0,
            "cap_active": True,
            "cap_applied": True,
            "numeric_cap_changed_score": True,
            "cap_reason": "Foundational gates failed or Unknown: G-02, G-03",
            "calculated_grade": "C",
            "effective_grade": "D",
            "calculated_maturity": "M2 — Defined",
            "effective_maturity": "M1 — Developing",
        },
        "assurance": {
            "index": 61.4,
            "label": "Moderate",
            "distribution": {"E0": 3, "E1": 2, "E2": 5, "E3": 25, "E4": 0},
        },
        "findings": [
            {
                "finding_id": "F-001",
                "control_id": "SPI-02",
                "dimension": "SPI",
                "condition": "No current production identity was available.",
                "priority": "Critical",
                "remediation": "Capture the live release identity.",
                "assurance": "E0",
                "gate": "G-02",
                "gate_status": "Unknown",
            },
            {
                "finding_id": "F-002",
                "control_id": "CGD-01",
                "dimension": "CGD",
                "condition": "One accepted Main change lacked a complete audit chain.",
                "priority": "Critical",
                "remediation": "Require a complete change trail.",
                "assurance": "E2",
                "gate": "G-03",
                "gate_status": "Fail",
            },
            {
                "finding_id": "F-003",
                "control_id": "SSC-01",
                "dimension": "SSC",
                "condition": "Credential prevention was not enabled.",
                "priority": "High",
                "remediation": "Enable credential prevention and response.",
                "assurance": "E2",
                "gate": None,
            },
        ],
        "limitations": [
            "The collector did not execute repository-owned build, deployment, recovery, or security code.",
            "Production evidence was unavailable to this run.",
        ],
        "dora": {
            "informative_only": True,
            "available": True,
            "service": "payments-api",
            "period_start": "2026-05-01",
            "period_end": "2026-07-31",
            "metrics": {
                "deployment_frequency": {"value": "12 per month", "window": "90 days"},
                "change_fail_rate": {"value": "8%", "window": "90 days"},
            },
        },
    }


class ReportingTests(unittest.TestCase):
    def test_plain_language_action_map_covers_all_35_controls(self) -> None:
        action_map = load_action_map(ACTION_MAP_PATH)
        self.assertEqual(len(action_map), 35)
        for control_id, item in action_map.items():
            with self.subTest(control_id=control_id):
                self.assertTrue(item["action"].endswith("."))
                self.assertTrue(item["owner_role"])
                self.assertTrue(item["why_it_matters"])
                self.assertTrue(item["expected_evidence_or_outcome"])

    def test_leadership_plan_has_at_most_seven_distinct_evidence_based_actions(self) -> None:
        assessment = assessment_fixture()
        summary = build_leadership_summary(assessment)
        actions = summary["top_actions"]
        self.assertEqual(len(actions), 7)
        self.assertEqual(len({item["action"] for item in actions}), 7)
        gap_controls = {
            control["control_id"]
            for control in assessment["controls"]
            if control["conformance"] in {"Partially met", "Unmet", "Unknown"}
        }
        for action in actions:
            self.assertTrue(set(action["control_ids"]).issubset(gap_controls))
            for required in (
                "owner_role",
                "why_it_matters",
                "expected_evidence_or_outcome",
                "standing_impact",
                "assessment_basis",
            ):
                self.assertTrue(action[required])
        unknown_action = next(
            item for item in actions if item["current_rating"] == "Unknown"
        )
        self.assertTrue(
            unknown_action["action"].startswith(
                "Confirm with current evidence whether this requirement is in place."
            )
        )
        self.assertIn("If it is not", unknown_action["action"])

    def test_authoritative_gate_status_drives_cap_priority(self) -> None:
        summary = build_leadership_summary(assessment_fixture())
        actions = summary["top_actions"]
        first_two = [item["control_ids"][0] for item in actions[:2]]
        self.assertEqual(first_two, ["CGD-01", "SPI-02"])
        spi_main_action = next(
            item for item in actions if item["control_ids"] == ["SPI-01"]
        )
        self.assertNotIn("identified reason for the D", spi_main_action["standing_impact"])
        self.assertNotIn("First because G-01", spi_main_action["priority_basis"])

    def test_reports_disclose_provisional_status_unknowns_and_separate_dora(self) -> None:
        assessment = assessment_fixture()
        detailed = render_health_assessment(assessment)
        leadership = render_leadership_summary(assessment)
        for report in (detailed, leadership):
            self.assertIn("0.1.0-draft", report)
            self.assertRegex(report.lower(), r"provisional")
            self.assertIn("informative only", report.lower())
        self.assertIn("No current production identity was available", detailed)
        self.assertIn(
            "did not have enough current evidence to confirm", leadership
        )
        self.assertIn("Next 7 actions, in order", leadership)
        self.assertIn("all 35", detailed.lower())

    def test_write_reports_uses_stable_names_and_compact_json_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = write_reports(assessment_fixture(), temporary)
            self.assertEqual(
                {path.name for path in paths.values()},
                {"health-assessment.md", "leadership-summary.md", "leadership-summary.json"},
            )
            for path in paths.values():
                self.assertTrue(path.is_file())
            summary = json.loads(paths["leadership_summary_json"].read_text(encoding="utf-8"))
            self.assertEqual(summary["schema_version"], "repository-health-leadership-summary/v1")
            self.assertEqual(summary["repository"]["name"], "example/payments")
            self.assertEqual(len(summary["top_actions"]), 7)
            self.assertTrue(summary["dora"]["informative_only"])
            self.assertNotIn("controls", summary)

    def test_no_action_is_fabricated_for_met_or_not_applicable_controls(self) -> None:
        assessment = assessment_fixture()
        for control in assessment["controls"]:
            control["conformance"] = "Met"
            control["points"] = 100
            control["assurance"] = "E3"
        assessment["controls"][-1]["conformance"] = "N/A"
        assessment["controls"][-1]["applicable"] = False
        assessment["controls"][-1]["points"] = None
        assessment["gates"] = {
            gate_id: {**gate, "status": "Pass"}
            for gate_id, gate in assessment["gates"].items()
        }
        assessment["findings"] = []
        summary = build_leadership_summary(assessment)
        self.assertEqual(summary["top_actions"], [])
        self.assertIn("No corrective action was generated", render_leadership_summary(assessment))

    def test_fewer_than_seven_gaps_produce_only_supported_actions(self) -> None:
        assessment = assessment_fixture()
        retained_gaps = {"SPI-02", "DCR-02"}
        for control in assessment["controls"]:
            if control["control_id"] not in retained_gaps:
                control["conformance"] = "Met"
                control["points"] = 100
                control["assurance"] = "E3"
        assessment["gates"]["G-01"]["status"] = "Pass"
        assessment["gates"]["G-03"]["status"] = "Pass"
        assessment["gates"]["G-04"]["status"] = "Pass"
        assessment["findings"] = [
            finding
            for finding in assessment["findings"]
            if finding["control_id"] in retained_gaps
        ]
        summary = build_leadership_summary(assessment)
        self.assertEqual(
            [item["control_ids"][0] for item in summary["top_actions"]],
            ["SPI-02", "DCR-02"],
        )
        self.assertIn("Next 2 actions, in order", render_leadership_summary(assessment))

    def test_untrusted_assessment_text_cannot_inject_markdown_or_html(self) -> None:
        assessment = assessment_fixture()
        attack = '<img src=x onerror=alert(1)>\n# forged heading\n![click](https://bad.invalid) **bold** | extra'
        assessment["repository"]["identity"] = attack
        assessment["limitations"] = [attack]
        assessment["controls"][1]["rationale"] = attack
        assessment["findings"][0]["condition"] = attack
        for report in (
            render_health_assessment(assessment),
            render_leadership_summary(assessment),
        ):
            self.assertNotIn("<img", report)
            self.assertNotIn("\n# forged heading", report)
            self.assertNotIn("![click]", report)
            self.assertNotIn("**bold**", report)
            self.assertIn("&lt;img", report)
            self.assertIn("\\!\\[click\\]", report)

    def test_incomplete_payload_does_not_claim_no_corrective_work(self) -> None:
        assessment = assessment_fixture()
        assessment["controls"] = []
        assessment["findings"] = []
        assessment["gates"] = {}
        summary = build_leadership_summary(assessment)
        self.assertEqual(summary["evidence"]["missing_standard_control_count"], 35)
        report = render_leadership_summary(assessment)
        self.assertIn("35 standard control results are missing", report)
        self.assertNotIn("Continue routine monitoring", report)

    def test_cli_accepts_assessment_flag_and_prints_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            assessment_path = root / "assessment.json"
            output_dir = root / "reports"
            assessment_path.write_text(json.dumps(assessment_fixture()), encoding="utf-8")
            process = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "automation.repository_health.reporting",
                    "--assessment",
                    str(assessment_path),
                    "--output-dir",
                    str(output_dir),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(process.returncode, 0, process.stderr)
            manifest = json.loads(process.stdout)
            self.assertEqual(Path(manifest["health_assessment"]).name, "health-assessment.md")
            self.assertTrue((output_dir / "leadership-summary.json").is_file())


if __name__ == "__main__":
    unittest.main()

"""Offline contract and packaging tests for bounded workflow evidence."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

from automation.repository_health.evidence_producer import (
    EvidenceStatementError,
    SCHEMA_VERSION,
    create_evidence_statement,
    load_evidence_statement,
    validate_evidence_bundle,
    validate_evidence_statement,
    verify_evidence_package,
    write_evidence_package,
)


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "automation" / "repository_health" / "evidence_producer.py"
ACTION = ROOT / ".github" / "actions" / "repository-health-evidence" / "action.yml"
CONTRACT = ROOT / "docs" / "evidence-producer.md"
SCHEMA_DOC = ROOT / "docs" / "artifact-schemas.md"

NOW = datetime(2026, 8, 9, 12, 0, 0, tzinfo=timezone.utc)
REPOSITORY = "TedTschopp/github-repository-health"
UNIT_ID = "repository-health-standard"
SUBJECT_SHA = "a" * 40
WORKFLOW_SHA = "b" * 40
SOURCE_DIGEST = "c" * 64
ARTIFACT_DIGEST = "d" * 64
WORKFLOW_REF = (
    "TedTschopp/github-repository-health/"
    ".github/workflows/repository-validation.yml@refs/heads/main"
)


def _digest(name: str, value: str = SOURCE_DIGEST) -> dict[str, str]:
    return {"name": name, "algorithm": "sha256", "value": value}


def _statement(
    *,
    kind: str = "validation",
    result: str = "success",
    artifacts: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    if artifacts is None:
        artifacts = [_digest("package", ARTIFACT_DIGEST)] if kind in {"release", "deployment"} else []
    return create_evidence_statement(
        repository=REPOSITORY,
        unit_id=UNIT_ID,
        subject_ref="refs/heads/main",
        subject_sha=SUBJECT_SHA,
        subject_digests=[_digest("source-input")],
        workflow_ref=WORKFLOW_REF,
        workflow_sha=WORKFLOW_SHA,
        run_id=123456789,
        run_attempt=2,
        observed_at="2026-08-09T05:00:00-07:00",
        kind=kind,
        result=result,
        categories=["unit-test", "build"],
        artifact_digests=artifacts,
        source_evidence_ids=["github-actions-run:123456789:2"],
        now=NOW,
    )


def _copy(value: object) -> object:
    return json.loads(json.dumps(value))


class EvidenceStatementTests(unittest.TestCase):
    def test_all_supported_kinds_create_canonical_valid_records(self) -> None:
        for kind in ("validation", "security", "release", "deployment"):
            with self.subTest(kind=kind):
                statement = _statement(kind=kind)
                validated = validate_evidence_statement(
                    statement,
                    expected_repository=REPOSITORY,
                    expected_unit_id=UNIT_ID,
                    expected_subject_sha=SUBJECT_SHA,
                    expected_workflow_ref=WORKFLOW_REF,
                    expected_workflow_sha=WORKFLOW_SHA,
                    expected_run_id=123456789,
                    expected_run_attempt=2,
                    now=NOW,
                )
                self.assertEqual(SCHEMA_VERSION, validated["schema_version"])
                self.assertRegex(validated["statement_id"], r"^sha256:[0-9a-f]{64}$")
                self.assertEqual("2026-08-09T12:00:00Z", validated["observed_at"])
                self.assertEqual(["build", "unit-test"], validated["categories"])
                self.assertEqual(
                    False,
                    validated["producer"]["producer_invoked_assessed_code"],
                )
                self.assertNotIn("assessed_code_executed", validated["producer"])

    def test_result_is_explicit_and_never_promoted_from_missing_data(self) -> None:
        unknown = _statement(result="unknown")
        self.assertEqual("unknown", unknown["result"])
        with self.assertRaisesRegex(EvidenceStatementError, "result must be"):
            create_evidence_statement(
                repository=REPOSITORY,
                unit_id=UNIT_ID,
                subject_ref="refs/heads/main",
                subject_sha=SUBJECT_SHA,
                subject_digests=[_digest("source-input")],
                workflow_ref=WORKFLOW_REF,
                workflow_sha=WORKFLOW_SHA,
                run_id=1,
                run_attempt=1,
                kind="validation",
                result=None,  # type: ignore[arg-type]
                categories=["build"],
                artifact_digests=[],
                source_evidence_ids=["check:1"],
                observed_at="2026-08-09T12:00:00Z",
                now=NOW,
            )
        with self.assertRaisesRegex(EvidenceStatementError, "release success requires"):
            _statement(kind="release", artifacts=[])
        release_failure = _statement(kind="release", result="failure", artifacts=[])
        self.assertEqual("failure", release_failure["result"])

    def test_duplicate_values_and_duplicate_statements_are_rejected(self) -> None:
        statement = _statement()

        duplicate_categories = _copy(statement)
        duplicate_categories["categories"] = ["build", "build"]
        with self.assertRaisesRegex(EvidenceStatementError, "duplicate value"):
            validate_evidence_statement(duplicate_categories, now=NOW)

        duplicate_sources = _copy(statement)
        duplicate_sources["source_evidence_ids"] = ["check:1", "check:1"]
        with self.assertRaisesRegex(EvidenceStatementError, "duplicate value"):
            validate_evidence_statement(duplicate_sources, now=NOW)

        duplicate_digests = _copy(statement)
        duplicate_digests["subject"]["digests"] = [
            _digest("source-input"),
            _digest("source-input", "e" * 64),
        ]
        with self.assertRaisesRegex(EvidenceStatementError, "duplicate digest name"):
            validate_evidence_statement(duplicate_digests, now=NOW)

        with self.assertRaisesRegex(EvidenceStatementError, "duplicate statement_id"):
            validate_evidence_bundle([statement, statement], now=NOW)

    def test_duplicate_json_fields_are_rejected_before_schema_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "statement.json"
            path.write_text(
                '{"schema_version":"one","schema_version":"two"}\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceStatementError, "duplicate JSON field"):
                load_evidence_statement(path, now=NOW)

    def test_nonfinite_and_floating_point_values_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "statement.json"
            path.write_text('{"value":NaN}\n', encoding="utf-8")
            with self.assertRaisesRegex(EvidenceStatementError, "non-finite"):
                load_evidence_statement(path, now=NOW)

        statement = _statement()
        statement["workflow"]["run_id"] = float("inf")
        with self.assertRaisesRegex(EvidenceStatementError, "non-finite"):
            validate_evidence_statement(statement, now=NOW)

        statement = _statement()
        statement["workflow"]["run_id"] = 1.0
        with self.assertRaisesRegex(EvidenceStatementError, "floating-point"):
            validate_evidence_statement(statement, now=NOW)

    def test_future_offset_free_and_ambiguous_inputs_fail_closed(self) -> None:
        future = _copy(_statement())
        future["observed_at"] = (NOW + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        with self.assertRaisesRegex(EvidenceStatementError, "future"):
            validate_evidence_statement(future, now=NOW)

        offset_free = _copy(_statement())
        offset_free["observed_at"] = "2026-08-09T12:00:00"
        with self.assertRaisesRegex(EvidenceStatementError, "UTC offset"):
            validate_evidence_statement(offset_free, now=NOW)

        ambiguous_ref = _copy(_statement())
        ambiguous_ref["subject"]["ref"] = "refs/heads/main..forged"
        with self.assertRaisesRegex(EvidenceStatementError, "unambiguous"):
            validate_evidence_statement(ambiguous_ref, now=NOW)

        wrong_repository_workflow = _copy(_statement())
        wrong_repository_workflow["workflow"]["ref"] = (
            "attacker/repository/.github/workflows/validation.yml@refs/heads/main"
        )
        with self.assertRaisesRegex(EvidenceStatementError, "exact repository"):
            validate_evidence_statement(wrong_repository_workflow, now=NOW)

        malicious_digest_name = _copy(_statement())
        malicious_digest_name["subject"]["digests"][0]["name"] = "../../payload"
        with self.assertRaisesRegex(EvidenceStatementError, "safe logical identifier"):
            validate_evidence_statement(malicious_digest_name, now=NOW)

        control_character = _copy(_statement())
        control_character["categories"] = ["build\nforged"]
        with self.assertRaisesRegex(EvidenceStatementError, "control characters"):
            validate_evidence_statement(control_character, now=NOW)

    def test_expected_identity_and_content_id_mismatches_fail(self) -> None:
        statement = _statement()
        with self.assertRaisesRegex(EvidenceStatementError, "subject.sha does not match"):
            validate_evidence_statement(
                statement,
                expected_subject_sha="f" * 40,
                now=NOW,
            )
        with self.assertRaisesRegex(EvidenceStatementError, "workflow.sha does not match"):
            validate_evidence_statement(
                statement,
                expected_workflow_sha="e" * 40,
                now=NOW,
            )
        with self.assertRaisesRegex(EvidenceStatementError, "unit_id does not match"):
            validate_evidence_statement(
                statement,
                expected_unit_id="different-unit",
                now=NOW,
            )

        tampered = _copy(statement)
        tampered["result"] = "failure"
        with self.assertRaisesRegex(EvidenceStatementError, "statement_id does not match"):
            validate_evidence_statement(tampered, now=NOW)

        uppercase_sha = _copy(statement)
        uppercase_sha["subject"]["sha"] = SUBJECT_SHA.upper()
        with self.assertRaisesRegex(EvidenceStatementError, "lowercase 40-character"):
            validate_evidence_statement(uppercase_sha, now=NOW)

    def test_package_round_trip_and_manifest_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence-statement.json"
            manifest = root / "SHA256SUMS"
            result = write_evidence_package(
                _statement(), output_path=evidence, manifest_path=manifest, now=NOW
            )
            self.assertRegex(result["sha256"], r"^[0-9a-f]{64}$")
            verified = verify_evidence_package(
                input_path=evidence,
                manifest_path=manifest,
                expected_repository=REPOSITORY,
                expected_subject_sha=SUBJECT_SHA,
                now=NOW,
            )
            self.assertEqual(result["statement_id"], verified["statement_id"])

            evidence.write_bytes(evidence.read_bytes() + b" ")
            with self.assertRaisesRegex(EvidenceStatementError, "SHA-256 does not match"):
                verify_evidence_package(
                    input_path=evidence, manifest_path=manifest, now=NOW
                )

    def test_cli_requires_result_and_validates_the_written_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence = root / "evidence-statement.json"
            manifest = root / "SHA256SUMS"
            base = [
                "python3",
                "-m",
                "automation.repository_health.evidence_producer",
                "create",
                "--repository",
                REPOSITORY,
                "--unit-id",
                UNIT_ID,
                "--subject-ref",
                "refs/heads/main",
                "--subject-sha",
                SUBJECT_SHA,
                "--subject-digest",
                f"source-input={SOURCE_DIGEST}",
                "--workflow-ref",
                WORKFLOW_REF,
                "--workflow-sha",
                WORKFLOW_SHA,
                "--run-id",
                "123456789",
                "--run-attempt",
                "2",
                "--observed-at",
                "2026-08-09T12:00:00Z",
                "--kind",
                "validation",
                "--category",
                "build",
                "--source-evidence-id",
                "github-actions-run:123456789:2",
                "--output",
                str(evidence),
                "--manifest",
                str(manifest),
            ]
            missing_result = subprocess.run(
                base,
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertNotEqual(0, missing_result.returncode)
            self.assertIn("--result", missing_result.stderr)

            created = subprocess.run(
                [*base, "--result", "success"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(0, created.returncode, created.stderr)
            created_result = json.loads(created.stdout)
            self.assertEqual(str(evidence.resolve()), created_result["evidence_path"])

            validated = subprocess.run(
                [
                    "python3",
                    "-m",
                    "automation.repository_health.evidence_producer",
                    "validate",
                    "--input",
                    str(evidence),
                    "--manifest",
                    str(manifest),
                    "--expected-repository",
                    REPOSITORY,
                    "--expected-unit-id",
                    UNIT_ID,
                    "--expected-subject-sha",
                    SUBJECT_SHA,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(0, validated.returncode, validated.stderr)
            self.assertTrue(json.loads(validated.stdout)["valid"])


class EvidenceActionPackagingTests(unittest.TestCase):
    def test_action_metadata_avoids_ambiguous_plain_scalars(self) -> None:
        text = ACTION.read_text(encoding="utf-8")
        self.assertNotIn("\t", text)
        self.assertRegex(text, r"(?m)^name: .+$")
        self.assertRegex(text, r"(?m)^runs:\n  using: composite$")
        for line in text.splitlines():
            match = re.match(r"^\s+description:\s+(.+)$", line)
            if match and ": " in match.group(1):
                self.assertTrue(
                    match.group(1).startswith(("'", '"', "|", ">")),
                    f"description with a colon must be quoted for YAML safety: {line}",
                )

    def test_composite_action_is_bounded_and_official_action_is_immutable(self) -> None:
        text = ACTION.read_text(encoding="utf-8")
        self.assertIn("using: composite", text)
        self.assertIn("python3 -I -c", text)
        self.assertIn('"repository_health",', text)
        self.assertIn('"evidence_producer.py",', text)
        self.assertIn("runpy.run_path", text)
        self.assertNotIn("runpy.run_module", text)
        self.assertIn("--expected-subject-sha", text)
        self.assertIn("--expected-unit-id", text)
        self.assertIn("--expected-workflow-sha", text)
        self.assertIn("--expected-run-attempt", text)
        self.assertIn("if: ${{ inputs.upload-artifact == 'true' }}", text)
        self.assertIn("producer_invoked_assessed_code", MODULE.read_text(encoding="utf-8"))
        self.assertNotIn("assessed_code_executed\"", MODULE.read_text(encoding="utf-8"))
        self.assertNotIn("actions/checkout@", text)
        self.assertIn(
            "name: repository-health-evidence--${{ inputs.unit-id }}",
            text,
        )
        self.assertNotIn("inputs.artifact-name", text)
        for forbidden in (" npm ", " make ", " pytest ", " docker ", " cargo ", " mvn ", " gradle "):
            self.assertNotIn(forbidden, f" {text.lower()} ")
        official_uses = re.findall(r"(?m)^\s+uses:\s+(actions/[^@\s]+)@([^\s#]+)", text)
        self.assertEqual([("actions/upload-artifact", "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a")], official_uses)
        self.assertTrue(all(re.fullmatch(r"[0-9a-f]{40}", revision) for _, revision in official_uses))

    def test_module_does_not_import_process_or_dynamic_execution_facilities(self) -> None:
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
        self.assertTrue({"exec", "eval", "system", "popen", "spawn"}.isdisjoint(calls))

    def test_isolated_launcher_ignores_consumer_python_shadows(self) -> None:
        text = ACTION.read_text(encoding="utf-8")
        match = re.search(
            r"python3 -I -c '\n(?P<code>.*?)\n        ' \"\$action_root\" \"\$@\"",
            text,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        code = textwrap.dedent(match.group("code"))
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary)
            marker = target / "consumer-code-executed"
            (target / "pathlib.py").write_text(
                f"open({str(marker)!r}, 'w').write('pathlib')\n", encoding="utf-8"
            )
            package = target / "automation" / "repository_health"
            package.mkdir(parents=True)
            (package / "evidence_producer.py").write_text(
                f"open({str(marker)!r}, 'w').write('package')\n", encoding="utf-8"
            )
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(target)
            result = subprocess.run(
                ["python3", "-I", "-c", code, str(ROOT), "--help"],
                cwd=target,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(marker.exists(), "consumer repository Python was imported")

    def test_documentation_keeps_job_scope_and_collection_boundaries_explicit(self) -> None:
        contract = CONTRACT.read_text(encoding="utf-8")
        schema = SCHEMA_DOC.read_text(encoding="utf-8")
        self.assertIn("not yet mapped into assessment controls or scores", contract)
        self.assertIn("does not currently change a repository-health score", contract)
        self.assertIn("producer_invoked_assessed_code: false", contract)
        self.assertIn("scoped only to the producer", contract)
        self.assertIn("must never be presented as a claim that the whole workflow job", schema)
        self.assertIn("do not affect an assessment result", schema)
        self.assertIn("full 40-character commit SHA", contract)


if __name__ == "__main__":
    unittest.main()

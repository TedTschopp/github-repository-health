from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from automation.repository_health.evidence_policy import (
    EvidencePolicyError,
    POLICY_SCHEMA,
    RUN_POPULATION_SCHEMA,
    SELECTION_RULE,
    load_evidence_policy,
    select_eligible_runs,
    validate_evidence_policy,
)


REPOSITORY = "octo/health"
MAIN_SHA = "a" * 40
RELEASE_SHA = "b" * 40


def policy(*statements: dict) -> dict:
    return {
        "schema_version": POLICY_SCHEMA,
        "repository": REPOSITORY,
        "units": [{"unit_id": "service-api", "statements": list(statements)}],
    }


def statement(**overrides: object) -> dict:
    value = {
        "kind": "validation",
        "categories": ["build", "unit-test"],
        "workflow_path": ".github/workflows/validate.yml",
        "subject_source": "assessed-main",
        "events": ["push"],
        "selection": SELECTION_RULE,
    }
    value.update(overrides)
    return value


def run(
    run_id: int,
    *,
    sha: str = MAIN_SHA,
    path: str = ".github/workflows/validate.yml@main",
    event: str = "push",
    updated_at: str = "2026-08-09T20:00:00Z",
) -> dict:
    run_ref = path.rsplit("@", 1)[1] if "@" in path else None
    return {
        "id": run_id,
        "run_attempt": 1,
        "head_sha": sha,
        "path": path,
        "head_branch": run_ref,
        "event": event,
        "status": "completed",
        "conclusion": "success",
        "updated_at": updated_at,
    }


def actions(*runs: dict, complete: bool = True, contract: dict | None = None) -> dict:
    return {
        "complete": complete,
        "population_complete": complete,
        "data": {
            "workflow_runs": list(runs),
            "population_contract": contract
            or {
                "schema_version": RUN_POPULATION_SCHEMA,
                "scope": "branch-window",
                "branch_ref": "refs/heads/main",
                "subjects": [],
            },
        },
    }


def controlled(raw: dict) -> dict:
    return load_evidence_policy(
        json.dumps(raw).encode("utf-8"),
        repository=REPOSITORY,
        unit_ids=["service-api"],
        source_sha=MAIN_SHA,
    )


class EvidencePolicyTests(unittest.TestCase):
    def test_validates_and_loads_duplicate_safe_policy(self) -> None:
        raw = policy(statement())
        normalized = validate_evidence_policy(
            raw,
            repository=REPOSITORY,
            unit_ids=["service-api"],
        )
        self.assertEqual("validation", normalized["units"][0]["statements"][0]["kind"])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "policy.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            loaded = load_evidence_policy(
                path,
                repository=REPOSITORY,
                unit_ids=["service-api"],
                source_sha=MAIN_SHA,
            )
            self.assertEqual(normalized["units"], loaded["units"])
            self.assertEqual(MAIN_SHA, loaded["_source"]["sha"])

    def test_rejects_duplicate_kind_and_unsafe_workflow(self) -> None:
        with self.assertRaises(EvidencePolicyError):
            validate_evidence_policy(
                policy(statement(), statement(categories=["lint"])),
                repository=REPOSITORY,
                unit_ids=["service-api"],
            )
        with self.assertRaises(EvidencePolicyError):
            validate_evidence_policy(
                policy(statement(workflow_path=".github/workflows/../owned.yml")),
                repository=REPOSITORY,
                unit_ids=["service-api"],
            )

    def test_selects_latest_exact_main_run_and_category_policy(self) -> None:
        controlled_policy = controlled(policy(statement()))
        selected = select_eligible_runs(
            controlled_policy,
            actions_observation=actions(
                run(10, updated_at="2026-08-09T19:00:00Z"),
                run(11, updated_at="2026-08-09T20:00:00Z"),
                run(12, sha="c" * 40, updated_at="2026-08-09T21:00:00Z"),
            ),
            main_sha=MAIN_SHA,
            main_branch="main",
        )
        self.assertTrue(selected["complete"])
        self.assertEqual({11: ["service-api"]}, selected["eligible_runs"])
        self.assertEqual(
            [f"{REPOSITORY}/.github/workflows/validate.yml@refs/heads/main"],
            selected["category_policy"]["service-api"]["validation"]["workflow_refs"],
        )

    def test_incomplete_population_and_equal_latest_runs_are_unknown(self) -> None:
        controlled_policy = controlled(policy(statement()))
        incomplete = select_eligible_runs(
            controlled_policy,
            actions_observation=actions(run(10), complete=False),
            main_sha=MAIN_SHA,
            main_branch="main",
        )
        self.assertEqual("unknown", incomplete["state"])
        self.assertIn("actions_population_incomplete", {gap["kind"] for gap in incomplete["gaps"]})
        ambiguous = select_eligible_runs(
            controlled_policy,
            actions_observation=actions(run(10), run(11)),
            main_sha=MAIN_SHA,
            main_branch="main",
        )
        self.assertEqual({}, ambiguous["eligible_runs"])
        self.assertIn("eligible_run_ambiguous", {gap["kind"] for gap in ambiguous["gaps"]})

    def test_production_unit_subject_uses_exact_tag_ref(self) -> None:
        controlled_policy = controlled(
            policy(
                statement(
                    kind="release",
                    categories=["package-publication"],
                    workflow_path=".github/workflows/release.yml",
                    subject_source="production-unit",
                    events=["release"],
                )
            ),
        )
        selected = select_eligible_runs(
            controlled_policy,
            actions_observation=actions(
                run(
                    20,
                    sha=RELEASE_SHA,
                    path=".github/workflows/release.yml@v1.2.3",
                    event="release",
                ),
                contract={
                    "schema_version": RUN_POPULATION_SCHEMA,
                    "scope": "exact-subjects",
                    "branch_ref": None,
                    "subjects": [
                        {"sha": RELEASE_SHA, "ref": "refs/tags/v1.2.3"}
                    ],
                },
            ),
            main_sha=MAIN_SHA,
            main_branch="main",
            production_subjects={
                "service-api": {"sha": RELEASE_SHA, "ref": "refs/tags/v1.2.3"}
            },
        )
        self.assertTrue(selected["complete"])
        self.assertEqual("refs/tags/v1.2.3", selected["selections"][0]["subject_ref"])

    def test_same_run_unit_for_two_kinds_is_unknown(self) -> None:
        controlled_policy = controlled(
            policy(
                statement(),
                statement(kind="security", categories=["sast"]),
            ),
        )
        selected = select_eligible_runs(
            controlled_policy,
            actions_observation=actions(run(10)),
            main_sha=MAIN_SHA,
            main_branch="main",
        )
        self.assertEqual({}, selected["eligible_runs"])
        self.assertIn("run_unit_artifact_collision", {gap["kind"] for gap in selected["gaps"]})

    def test_wrong_run_ref_and_unbound_policy_cannot_select(self) -> None:
        controlled_policy = controlled(policy(statement()))
        selected = select_eligible_runs(
            controlled_policy,
            actions_observation=actions(run(10, path=".github/workflows/validate.yml@attacker")),
            main_sha=MAIN_SHA,
            main_branch="main",
        )
        self.assertEqual({}, selected["eligible_runs"])
        self.assertIn("eligible_run_missing", {gap["kind"] for gap in selected["gaps"]})
        with self.assertRaisesRegex(EvidencePolicyError, "bound to an exact Main"):
            select_eligible_runs(
                validate_evidence_policy(
                    policy(statement()), repository=REPOSITORY, unit_ids=["service-api"]
                ),
                actions_observation=actions(run(10)),
                main_sha=MAIN_SHA,
                main_branch="main",
            )


if __name__ == "__main__":
    unittest.main()

"""Adversarial tests for trusted exact-Main delivery fact construction."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess
import tempfile
import unittest

from automation.repository_health.delivery_facts import (
    ACTIONS_RUN_POPULATION_SCHEMA,
    FACT_BUILDER_SCHEMA,
    build_delivery_facts,
)
from automation.repository_health.delivery_resolution import (
    ANCESTRY_FACT_SCHEMA,
    INTERVENING_CHECK_FACT_SCHEMA,
)


REPOSITORY = "example/delivery-facts"
CHECK = "Validate Main"
WORKFLOW = ".github/workflows/validate.yml"
WORKFLOW_ID = 771
WORKFLOW_REF = "refs/heads/main"


def _run(*arguments: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        list(arguments),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _config(*, controlled: bool = True) -> dict:
    repository: dict = {"authoritative_checks": [CHECK]}
    if controlled:
        repository["authoritative_check_identities"] = {
            CHECK: {
                "workflow_id": WORKFLOW_ID,
                "workflow_path": WORKFLOW,
                "workflow_ref": WORKFLOW_REF,
                "job": CHECK,
            }
        }
    return {"repository": repository}


def _identity(source_sha: str, correspondence: str = "Releasable-Main") -> dict:
    return {
        "units": [
            {
                "unit_id": "app",
                "correspondence": correspondence,
                "source_sha": source_sha,
                "validation": {"authoritative_checks": [CHECK]},
            }
        ]
    }


def _attempt(
    run_id: int,
    sha: str,
    *,
    attempt: int = 1,
    conclusion: str | None = "success",
    status: str = "completed",
    workflow_id: int = WORKFLOW_ID,
    workflow_path: str = WORKFLOW,
    workflow_ref: str = WORKFLOW_REF,
) -> dict:
    return {
        "run_id": run_id,
        "attempt": attempt,
        "run": {
            "id": run_id,
            "run_attempt": attempt,
            "head_sha": sha,
            "status": status,
            "conclusion": conclusion,
            "workflow_id": workflow_id,
            "path": f"{workflow_path}@{workflow_ref}",
        },
        "jobs": [
            {
                "id": run_id * 100 + attempt,
                "run_id": run_id,
                "run_attempt": attempt,
                "name": CHECK,
                "head_sha": sha,
                "status": status,
                "conclusion": conclusion,
            }
        ],
        "complete": True,
        "population_complete": True,
    }


def _observations(main_sha: str, rows: list[dict]) -> dict:
    latest: dict[int, dict] = {}
    for row in rows:
        run_id = row["run_id"]
        if run_id not in latest or row["attempt"] > latest[run_id]["attempt"]:
            latest[run_id] = row
    workflow_runs = [
        {
            "id": run_id,
            "run_attempt": row["attempt"],
            "head_sha": row["run"]["head_sha"],
            "workflow_id": row["run"]["workflow_id"],
            "path": row["run"]["path"],
        }
        for run_id, row in sorted(latest.items())
    ]
    return {
        "observations": {
            "actions_w365": {
                "state": "observed",
                "complete": True,
                "population_complete": True,
                "subject_sha": main_sha,
                "gaps": [],
                "data": {
                    "population_contract": {
                        "schema_version": ACTIONS_RUN_POPULATION_SCHEMA,
                        "scope": "branch-window",
                        "branch_ref": "refs/heads/main",
                        "subjects": [],
                    },
                    "request_budget": {"maximum": 1000, "used": 20},
                    "workflow_runs": workflow_runs,
                    "run_attempts": rows,
                },
            }
        }
    }


class DeliveryFactTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        _run("git", "init", "-q", cwd=self.root)
        _run("git", "config", "user.name", "Repository Health", cwd=self.root)
        _run("git", "config", "user.email", "health@example.invalid", cwd=self.root)
        self.source = self._commit("source")
        self.middle = self._commit("middle")
        self.main = self._commit("main")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _commit(self, text: str) -> str:
        path = self.root / "content.txt"
        path.write_text(f"{text}\n", encoding="utf-8")
        _run("git", "add", "content.txt", cwd=self.root)
        _run("git", "commit", "-q", "-m", text, cwd=self.root)
        return _run("git", "rev-parse", "HEAD", cwd=self.root)

    def _build(
        self,
        *,
        source: str | None = None,
        main: str | None = None,
        correspondence: str = "Releasable-Main",
        rows: list[dict] | None = None,
        observations: dict | None = None,
        config: dict | None = None,
        root: Path | None = None,
        max_revisions: int = 5000,
    ) -> dict:
        selected_source = source or self.source
        selected_main = main or self.main
        if rows is None:
            rows = [
                _attempt(101, self.middle),
                _attempt(102, self.main),
            ]
        return build_delivery_facts(
            root or self.root,
            repository=REPOSITORY,
            exact_main_sha=selected_main,
            production_identity=_identity(selected_source, correspondence),
            github_observations=(
                observations if observations is not None else _observations(selected_main, rows)
            ),
            config=config or _config(),
            max_revisions=max_revisions,
        )

    def test_exact_main_builds_exact_verified_empty_facts_without_history_telemetry(self) -> None:
        result = self._build(
            source=self.main,
            correspondence="Exact-Main",
            observations={},
            config=_config(controlled=False),
        )

        self.assertEqual(FACT_BUILDER_SCHEMA, result["schema_version"])
        ancestry = result["ancestry_facts"][0]
        checks = result["intervening_check_facts"][0]
        self.assertEqual(ANCESTRY_FACT_SCHEMA, ancestry["schema_version"])
        self.assertEqual(INTERVENING_CHECK_FACT_SCHEMA, checks["schema_version"])
        self.assertEqual(
            ("verified", True, True),
            (ancestry["state"], ancestry["population_complete"], ancestry["reachable_from_main"]),
        )
        self.assertEqual(("verified", True, []), (checks["state"], checks["population_complete"], checks["revisions"]))
        self.assertEqual([], result["gaps"])

    def test_releasable_main_requires_complete_ordered_first_parent_checks(self) -> None:
        result = self._build()

        fact = result["intervening_check_facts"][0]
        self.assertEqual(("verified", True), (fact["state"], fact["population_complete"]))
        self.assertEqual([self.middle, self.main], [row["sha"] for row in fact["revisions"]])
        self.assertEqual(
            [[{"name": CHECK, "conclusion": "success"}]] * 2,
            [row["checks"] for row in fact["revisions"]],
        )

    def test_omitted_middle_revision_is_unknown_not_inferred_from_main(self) -> None:
        result = self._build(rows=[_attempt(102, self.main)])

        fact = result["intervening_check_facts"][0]
        self.assertEqual(("unknown", False, []), (fact["state"], fact["population_complete"], fact["revisions"]))
        self.assertIn("authoritative_check_missing", {gap["code"] for gap in result["gaps"]})

    def test_spoofed_same_name_job_from_other_workflow_cannot_satisfy_identity(self) -> None:
        mutations = {
            "workflow_id": {"workflow_id": WORKFLOW_ID + 1},
            "workflow_path": {"workflow_path": ".github/workflows/lookalike.yml"},
            "workflow_ref": {"workflow_ref": "refs/heads/lookalike"},
        }
        for label, mutation in mutations.items():
            with self.subTest(label=label):
                result = self._build(
                    rows=[
                        _attempt(101, self.middle, **mutation),
                        _attempt(102, self.main, **mutation),
                    ]
                )

                self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
                self.assertIn(
                    "authoritative_check_identity_mismatch",
                    {gap["code"] for gap in result["gaps"]},
                )

    def test_missing_controlled_identity_keeps_name_only_matches_unknown(self) -> None:
        result = self._build(config=_config(controlled=False))

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("check_identities_incomplete", {gap["code"] for gap in result["gaps"]})

    def test_partial_controlled_identity_is_unknown(self) -> None:
        config = _config()
        del config["repository"]["authoritative_check_identities"][CHECK]["workflow_ref"]

        result = self._build(config=config)

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("check_identity_invalid", {gap["code"] for gap in result["gaps"]})

    def test_one_identity_cannot_cover_two_authoritative_checks(self) -> None:
        second_check = "Security scan"
        config = _config()
        config["repository"]["authoritative_checks"] = [CHECK, second_check]
        identity = _identity(self.source)
        identity["units"][0]["validation"]["authoritative_checks"] = [CHECK, second_check]

        result = build_delivery_facts(
            self.root,
            repository=REPOSITORY,
            exact_main_sha=self.main,
            production_identity=identity,
            github_observations=_observations(
                self.main,
                [_attempt(101, self.middle), _attempt(102, self.main)],
            ),
            config=config,
        )

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("check_identities_incomplete", {gap["code"] for gap in result["gaps"]})

    def test_workflow_path_without_observed_ref_suffix_is_unknown(self) -> None:
        observation = _observations(
            self.main,
            [_attempt(101, self.middle), _attempt(102, self.main)],
        )
        group = observation["observations"]["actions_w365"]["data"]
        group["workflow_runs"][0]["path"] = WORKFLOW
        group["run_attempts"][0]["run"]["path"] = WORKFLOW

        result = self._build(observations=observation)

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("workflow_run_invalid", {gap["code"] for gap in result["gaps"]})

    def test_latest_rerun_supersedes_failed_prior_attempt(self) -> None:
        rows = [
            _attempt(101, self.middle),
            _attempt(102, self.main, attempt=1, conclusion="failure"),
            _attempt(102, self.main, attempt=2, conclusion="success"),
        ]
        result = self._build(rows=rows)

        fact = result["intervening_check_facts"][0]
        self.assertEqual("verified", fact["state"])
        self.assertEqual("success", fact["revisions"][-1]["checks"][0]["conclusion"])

    def test_explicit_terminal_failure_is_verified_as_unsuccessful(self) -> None:
        result = self._build(
            rows=[
                _attempt(101, self.middle),
                _attempt(102, self.main, conclusion="failure"),
            ]
        )

        fact = result["intervening_check_facts"][0]
        self.assertEqual(("verified", True), (fact["state"], fact["population_complete"]))
        self.assertEqual("failure", fact["revisions"][-1]["checks"][0]["conclusion"])

    def test_latest_nonterminal_check_is_unknown(self) -> None:
        result = self._build(
            rows=[
                _attempt(101, self.middle),
                _attempt(102, self.main, status="in_progress", conclusion=None),
            ]
        )

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("authoritative_check_nonterminal", {gap["code"] for gap in result["gaps"]})

    def test_duplicate_attempt_population_is_unknown(self) -> None:
        rows = [_attempt(101, self.middle), _attempt(102, self.main)]
        observation = _observations(self.main, rows)
        observation["observations"]["actions_w365"]["data"]["run_attempts"].append(
            deepcopy(rows[-1])
        )
        result = self._build(observations=observation)

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("workflow_attempt_duplicate", {gap["code"] for gap in result["gaps"]})

    def test_request_budget_gap_is_unknown(self) -> None:
        observation = _observations(
            self.main,
            [_attempt(101, self.middle), _attempt(102, self.main)],
        )
        observation["observations"]["actions_w365"]["data"]["request_budget"] = {
            "maximum": 10,
            "used": 11,
        }
        result = self._build(observations=observation)

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("actions_request_budget_unverified", {gap["code"] for gap in result["gaps"]})

    def test_revision_budget_is_unknown(self) -> None:
        result = self._build(max_revisions=1)

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("first_parent_budget", {gap["code"] for gap in result["gaps"]})

    def test_missing_source_object_is_unknown(self) -> None:
        result = self._build(source="f" * 40)

        self.assertEqual("unknown", result["ancestry_facts"][0]["state"])
        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("source_object_missing", {gap["code"] for gap in result["gaps"]})

    def test_shallow_repository_is_unknown_even_when_exact_main_object_exists(self) -> None:
        clone = Path(self.temporary.name) / "shallow"
        _run("git", "clone", "-q", "--depth", "1", f"file://{self.root}", str(clone))
        shallow_main = _run("git", "rev-parse", "HEAD", cwd=clone)

        result = self._build(
            source=shallow_main,
            main=shallow_main,
            correspondence="Exact-Main",
            observations={},
            root=clone,
        )

        self.assertEqual("unknown", result["ancestry_facts"][0]["state"])
        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("shallow_repository", {gap["code"] for gap in result["gaps"]})

    def test_complete_nonancestor_is_a_verified_violation(self) -> None:
        _run("git", "checkout", "-q", "--orphan", "unrelated", cwd=self.root)
        unrelated_path = self.root / "unrelated.txt"
        unrelated_path.write_text("unrelated\n", encoding="utf-8")
        _run("git", "add", "unrelated.txt", cwd=self.root)
        _run("git", "commit", "-q", "-m", "unrelated", cwd=self.root)
        unrelated = _run("git", "rev-parse", "HEAD", cwd=self.root)

        result = self._build(source=unrelated, observations={})

        ancestry = result["ancestry_facts"][0]
        self.assertEqual(
            ("verified", True, False),
            (ancestry["state"], ancestry["population_complete"], ancestry["reachable_from_main"]),
        )
        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("source_not_reachable", {gap["code"] for gap in result["gaps"]})

    def test_observation_bound_to_different_main_is_unknown(self) -> None:
        observation = _observations(
            self.middle,
            [_attempt(101, self.middle), _attempt(102, self.main)],
        )
        result = self._build(observations=observation)

        self.assertEqual("unknown", result["intervening_check_facts"][0]["state"])
        self.assertIn("actions_population_incomplete", {gap["code"] for gap in result["gaps"]})


if __name__ == "__main__":
    unittest.main()

"""Contract and adversarial tests for heterogeneous production identities."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from automation.repository_health.configuration import load_config
from automation.repository_health.engine import assess_repository
from automation.repository_health.normalizers import load_production_identity as load_legacy_identity
from automation.repository_health.production_identity import (
    ACTIVE_PROFILES,
    ARCHIVE_MAIN_POLICY,
    GENERIC_PRODUCTION_SCHEMA,
    MAIN_AHEAD_POLICY,
    NO_OUTPUT_MAIN_POLICY,
    ProductionIdentityError,
    declared_release_asset_names,
    load_production_identity,
    validate_generic_production_identity,
)


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = "example/heterogeneous-repository"
VERSION = "0.1.0-draft"
SOURCE_SHA = "a" * 40
OTHER_SHA = "b" * 40
DIGEST = "c" * 64
CHECK = "Validate Main"


def _config(unit_ids: list[str], correspondence: str, checks: list[str] | None = None) -> dict:
    return {
        "standard": {"version": VERSION},
        "repository": {
            "authoritative_checks": [CHECK] if checks is None else checks,
            "deployable_units": unit_ids,
            "production_correspondence": correspondence,
        },
    }


def _validation(profile: str) -> dict:
    if profile in ACTIVE_PROFILES:
        reachable = True
        main_policy = MAIN_AHEAD_POLICY
    elif profile == "archived-retired":
        reachable = True
        main_policy = ARCHIVE_MAIN_POLICY
    else:
        reachable = False
        main_policy = NO_OUTPUT_MAIN_POLICY
    return {
        "authoritative_checks": [CHECK],
        "source_must_be_reachable_from_main": reachable,
        "main_ahead_policy": main_policy,
        "system_of_record_proof_required": True,
        "incomplete_system_of_record_result": "Unknown",
    }


def _unit(profile: str, unit_id: str = "unit") -> dict:
    common = {
        "unit_id": unit_id,
        "profile": profile,
        "lifecycle": "Active",
        "correspondence": "Releasable-Main",
        "source_sha": SOURCE_SHA,
        "validation": _validation(profile),
        "limitations": ["The declaration still requires live system-of-record verification."],
    }
    if profile == "application-github-deployment":
        common["selector"] = {
            "system": "github-deployments",
            "strategy": "exact-deployment-id",
            "environment": "production",
            "deployment_id": 401,
            "required_status": "success",
            "artifact": {
                "reference": "ghcr.io/example/application@sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
                "sha256": DIGEST,
            },
        }
    elif profile == "package-github-release":
        common["selector"] = {
            "system": "github-releases",
            "strategy": "exact-release-id-and-tag",
            "release_id": 501,
            "tag": "v2.4.0",
            "allow_draft": False,
            "allow_prerelease": False,
            "artifacts": [
                {"name": "package-2.4.0.tar.gz", "sha256": DIGEST, "primary": True},
            ],
        }
    elif profile == "gitops-production-ref":
        common["correspondence"] = "Production-Ref"
        common["selector"] = {
            "system": "git",
            "strategy": "exact-ref-commit-and-path",
            "production_ref": "refs/heads/production",
            "ref_commit_sha": SOURCE_SHA,
            "path": "environments/production",
            "content_sha256": DIGEST,
        }
    elif profile == "documentation-publication":
        common["selector"] = {
            "system": "github-pages",
            "strategy": "exact-pages-deployment-id",
            "environment": "github-pages",
            "deployment_id": 601,
            "publication_url": "https://docs.example.invalid/guide/",
            "content_sha256": DIGEST,
            "required_status": "success",
        }
    elif profile == "approved-no-current-output":
        common.update(
            {
                "lifecycle": "Experimental",
                "correspondence": "N/A",
                "source_sha": None,
                "selector": {
                    "system": "governance-decision",
                    "strategy": "approved-no-current-output",
                    "decision_id": "DEC-2026-0042",
                    "approved_by": "Architecture Review Board",
                    "approved_at": "2026-08-01",
                    "review_date": "2026-11-01",
                    "reason": "The experiment has no deployed, published, or supported output.",
                    "consumer_discovery": "Portfolio and dependency searches found no supported consumers.",
                },
            }
        )
    elif profile == "archived-retired":
        common.update(
            {
                "lifecycle": "Archived",
                "correspondence": "N/A",
                "source_sha": None,
                "selector": {
                    "system": "governance-decision",
                    "strategy": "archive-disposition",
                    "disposition": "Archived",
                    "decision_id": "RET-2026-0007",
                    "approved_by": "Portfolio Owner",
                    "effective_at": "2026-07-31",
                    "last_known_source_sha": OTHER_SHA,
                    "last_known_output": {
                        "status": "identified",
                        "kind": "release",
                        "identity": "release:v1.8.3",
                        "reason": None,
                    },
                    "write_protected": True,
                },
            }
        )
    else:
        raise AssertionError(f"unsupported fixture profile: {profile}")
    return common


def _record(unit: dict) -> dict:
    return {
        "schema_version": GENERIC_PRODUCTION_SCHEMA,
        "standard_version": VERSION,
        "repository": REPOSITORY,
        "units": [unit],
    }


def _validate_one(unit: dict) -> dict:
    return validate_generic_production_identity(
        _record(unit),
        config=_config([unit["unit_id"]], unit["correspondence"]),
        repository=REPOSITORY,
    )


class ProductionIdentityProfileTests(unittest.TestCase):
    def assert_valid_profile(self, profile: str) -> dict:
        unit = _unit(profile)
        result = _validate_one(unit)
        self.assertEqual(profile, result["units"][0]["profile"])
        self.assertTrue(result["units"][0]["validation"]["system_of_record_proof_required"])
        self.assertEqual(
            "Unknown",
            result["units"][0]["validation"]["incomplete_system_of_record_result"],
        )
        if profile in ACTIVE_PROFILES:
            self.assertEqual(SOURCE_SHA, result["units"][0]["source_sha"])
        else:
            self.assertIsNone(result["units"][0]["source_sha"])
        return result

    def test_application_github_deployment_profile(self) -> None:
        result = self.assert_valid_profile("application-github-deployment")
        self.assertEqual(401, result["units"][0]["selector"]["deployment_id"])

    def test_package_github_release_profile(self) -> None:
        result = self.assert_valid_profile("package-github-release")
        self.assertEqual("v2.4.0", result["units"][0]["selector"]["tag"])
        self.assertEqual(
            ["package-2.4.0.tar.gz"],
            declared_release_asset_names(result),
        )

    def test_gitops_production_ref_profile(self) -> None:
        result = self.assert_valid_profile("gitops-production-ref")
        self.assertEqual(SOURCE_SHA, result["units"][0]["selector"]["ref_commit_sha"])

    def test_documentation_publication_profile_supports_pages_and_deployments(self) -> None:
        self.assert_valid_profile("documentation-publication")
        pages_sha = _unit("documentation-publication")
        pages_sha["selector"]["deployment_id"] = SOURCE_SHA
        self.assertEqual(
            SOURCE_SHA,
            _validate_one(pages_sha)["units"][0]["selector"]["deployment_id"],
        )
        deployment = _unit("documentation-publication")
        deployment["selector"].update(
            {
                "system": "github-deployments",
                "strategy": "exact-deployment-id",
                "environment": "documentation-production",
            }
        )
        _validate_one(deployment)

    def test_explicit_approved_no_current_output_profile(self) -> None:
        result = self.assert_valid_profile("approved-no-current-output")
        self.assertEqual("N/A", result["units"][0]["correspondence"])

    def test_archived_retired_profile_supports_both_dispositions(self) -> None:
        self.assert_valid_profile("archived-retired")
        retired = _unit("archived-retired")
        retired["lifecycle"] = "Retired"
        retired["selector"]["disposition"] = "Retired"
        _validate_one(retired)

        never_released = _unit("archived-retired")
        never_released["selector"]["last_known_output"] = {
            "status": "none",
            "kind": None,
            "identity": None,
            "reason": "No supported output was ever released.",
        }
        _validate_one(never_released)


class ProductionIdentityCompatibilityTests(unittest.TestCase):
    def test_legacy_self_release_retains_identical_validation_output(self) -> None:
        config = load_config(ROOT / ".github" / "repository-health.toml")
        source = ROOT / ".github" / "repository-health-production.json"
        expected = load_legacy_identity(
            source,
            config=config,
            repository="TedTschopp/github-repository-health",
        )
        actual = load_production_identity(
            source,
            config=config,
            repository="TedTschopp/github-repository-health",
        )
        self.assertEqual(expected, actual)
        self.assertEqual(
            [
                artifact["name"]
                for artifact in expected["units"][0]["current"]["artifacts"]
            ],
            declared_release_asset_names(actual),
        )

    def test_legacy_release_contract_is_not_weakened(self) -> None:
        config = load_config(ROOT / ".github" / "repository-health.toml")
        value = json.loads(
            (ROOT / ".github" / "repository-health-production.json").read_text(encoding="utf-8")
        )
        value["units"][0]["current"]["attestations"] = []
        with self.assertRaises(ProductionIdentityError):
            load_production_identity(
                value,
                config=config,
                repository="TedTschopp/github-repository-health",
            )


class ProductionIdentityEngineIntegrationTests(unittest.TestCase):
    def test_engine_download_allowlist_is_package_only_and_generic_metrics_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository_root = Path(temporary)
            subprocess.run(["git", "init", "-b", "main", str(repository_root)], check=True, capture_output=True)
            subprocess.run(
                ["git", "-C", str(repository_root), "config", "user.name", "Production Identity Test"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository_root), "config", "user.email", "identity@example.invalid"],
                check=True,
            )
            github = repository_root / ".github"
            github.mkdir()
            config_path = github / "repository-health.toml"
            config_path.write_text(
                f'''[standard]
version = "{VERSION}"

[repository]
main_branch = "main"
authoritative_checks = ["{CHECK}"]
deployable_units = ["app", "package"]
production_correspondence = "Releasable-Main"
''',
                encoding="utf-8",
            )
            (repository_root / "README.md").write_text("controlled source\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(repository_root), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repository_root), "commit", "-m", "Create controlled source"],
                check=True,
                capture_output=True,
            )
            source_sha = subprocess.run(
                ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()

            application = _unit("application-github-deployment", "app")
            application["source_sha"] = source_sha
            application_reference = application["selector"]["artifact"]["reference"]
            package = _unit("package-github-release", "package")
            package["source_sha"] = source_sha
            production = {
                "schema_version": GENERIC_PRODUCTION_SCHEMA,
                "standard_version": VERSION,
                "repository": REPOSITORY,
                "units": [application, package],
            }
            (github / "repository-health-production.json").write_text(
                json.dumps(production, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "-C", str(repository_root), "add", ".github/repository-health-production.json"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(repository_root), "commit", "-m", "Declare generic production units"],
                check=True,
                capture_output=True,
            )

            captured_names: list[str] = []

            def fake_observations(repository: str, **kwargs: object) -> dict:
                captured_names.extend(kwargs.get("release_asset_names", []))  # type: ignore[arg-type]
                return {
                    "schema_version": "RH-GITHUB-OBSERVATIONS-1.0",
                    "observed_at": "2026-08-09T20:00:00+00:00",
                    "repository": repository,
                    "subject_sha": kwargs["subject_sha"],
                    "unit": None,
                    "units": [],
                    "state": "unknown",
                    "completeness": "unknown",
                    "complete": False,
                    "population_complete": False,
                    "observations": {},
                    "gaps": [{"kind": "fixture", "message": "No runtime proof supplied."}],
                }

            history = {
                "state": "unknown",
                "complete": False,
                "branch": "repository-health-evidence",
                "branch_sha": None,
                "snapshots": [],
                "gaps": ["Fixture has no durable history."],
            }
            with (
                patch(
                    "automation.repository_health.engine.collect_github_observations",
                    side_effect=fake_observations,
                ),
                patch(
                    "automation.repository_health.engine.collect_remote_history",
                    return_value=history,
                ),
            ):
                assessment = assess_repository(
                    repository=repository_root,
                    catalog_path=ROOT / "docs" / "control-catalog.md",
                    config_path=config_path,
                    github_repository=REPOSITORY,
                    github_observation_client=object(),  # type: ignore[arg-type]
                    now=datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc),
                )

            self.assertEqual(["package-2.4.0.tar.gz"], captured_names)
            self.assertNotIn(application_reference, captured_names)
            normalization = assessment["facts"]["github"]["normalization"]
            self.assertTrue(normalization["production_identity_valid"])
            metric = next(
                item
                for item in assessment["measurements"]
                if item["metric_id"] == "M-SPI-02S" and item["unit_id"] is None
            )
            self.assertEqual("unknown", metric["state"])


class ProductionIdentityAdversarialTests(unittest.TestCase):
    def assert_invalid(self, unit: dict, pattern: str | None = None) -> None:
        context = self.assertRaisesRegex(ProductionIdentityError, pattern) if pattern else self.assertRaises(ProductionIdentityError)
        with context:
            _validate_one(unit)

    def test_duplicate_unknown_and_unsupported_json_are_rejected(self) -> None:
        record = _record(_unit("application-github-deployment"))
        raw = json.dumps(record, sort_keys=True)
        duplicate = raw.replace(
            f'"schema_version": "{GENERIC_PRODUCTION_SCHEMA}"',
            f'"schema_version": "{GENERIC_PRODUCTION_SCHEMA}", "schema_version": "{GENERIC_PRODUCTION_SCHEMA}"',
            1,
        ).encode("utf-8")
        config = _config(["unit"], "Releasable-Main")
        with self.assertRaisesRegex(ProductionIdentityError, "duplicate JSON key"):
            load_production_identity(duplicate, config=config, repository=REPOSITORY)

        for location in ("top", "unit", "selector", "validation"):
            with self.subTest(location=location):
                changed = deepcopy(record)
                target = {
                    "top": changed,
                    "unit": changed["units"][0],
                    "selector": changed["units"][0]["selector"],
                    "validation": changed["units"][0]["validation"],
                }[location]
                target["uncontrolled"] = True
                with self.assertRaisesRegex(ProductionIdentityError, "unknown keys"):
                    load_production_identity(
                        json.dumps(changed).encode("utf-8"),
                        config=config,
                        repository=REPOSITORY,
                    )

        unsupported = deepcopy(record)
        unsupported["schema_version"] = "RH-PRODUCTION-IDENTITY-999.0"
        with self.assertRaisesRegex(ProductionIdentityError, "unsupported production identity schema"):
            load_production_identity(unsupported, config=config, repository=REPOSITORY)

    def test_all_active_profiles_require_immutable_source_and_correspondence(self) -> None:
        for profile in sorted(ACTIVE_PROFILES):
            for field, invalid in (("source_sha", None), ("source_sha", "A" * 40), ("correspondence", "N/A")):
                with self.subTest(profile=profile, field=field, invalid=invalid):
                    unit = _unit(profile)
                    unit[field] = invalid
                    self.assert_invalid(unit)

    def test_active_and_archive_lifecycles_are_disjoint(self) -> None:
        experimental = _unit("application-github-deployment")
        experimental["lifecycle"] = "Experimental"
        _validate_one(experimental)

        archived_output = _unit("package-github-release")
        archived_output["lifecycle"] = "Archived"
        self.assert_invalid(archived_output, "invalid for an active output")

    def test_runtime_proof_policy_cannot_be_declared_pass_or_optional(self) -> None:
        for profile in sorted(ACTIVE_PROFILES | {"approved-no-current-output", "archived-retired"}):
            with self.subTest(profile=profile, mutation="optional"):
                unit = _unit(profile)
                unit["validation"]["system_of_record_proof_required"] = False
                self.assert_invalid(unit, "system-of-record proof")
            with self.subTest(profile=profile, mutation="pass"):
                unit = _unit(profile)
                unit["validation"]["incomplete_system_of_record_result"] = "Pass"
                self.assert_invalid(unit, "fail incomplete")

    def test_stale_no_output_declaration_remains_unproven_until_downstream_verification(self) -> None:
        unit = _unit("approved-no-current-output")
        unit["selector"]["approved_at"] = "2019-01-01"
        unit["selector"]["review_date"] = "2020-01-01"
        result = _validate_one(unit)["units"][0]
        self.assertTrue(result["validation"]["system_of_record_proof_required"])
        self.assertEqual("Unknown", result["validation"]["incomplete_system_of_record_result"])
        self.assertNotIn("conformance", result)

    def test_every_profile_selector_rejects_unknown_keys(self) -> None:
        for profile in sorted(ACTIVE_PROFILES | {"approved-no-current-output", "archived-retired"}):
            with self.subTest(profile=profile):
                unit = _unit(profile)
                unit["selector"]["uncontrolled"] = True
                self.assert_invalid(unit, "unknown keys")

    def test_application_deployment_requires_immutable_artifact_identity(self) -> None:
        missing = _unit("application-github-deployment")
        missing["selector"].pop("artifact")
        self.assert_invalid(missing, "missing required keys")

        malformed = _unit("application-github-deployment")
        malformed["selector"]["artifact"]["sha256"] = "mutable-latest"
        self.assert_invalid(malformed, "SHA-256 digest")

        unknown = _unit("application-github-deployment")
        unknown["selector"]["artifact"]["uncontrolled"] = True
        self.assert_invalid(unknown, "unknown keys")

    def test_profile_selectors_reject_mutable_ambiguous_or_conflicting_identity(self) -> None:
        cases: list[tuple[str, callable, str]] = []

        deployment = _unit("application-github-deployment")
        deployment["selector"]["strategy"] = "latest-successful"
        cases.append(("mutable deployment", lambda: deployment, "exact GitHub deployment"))

        package = _unit("package-github-release")
        package["selector"]["tag"] = "latest"
        cases.append(("latest release alias", lambda: package, "mutable channel alias"))

        duplicate_assets = _unit("package-github-release")
        duplicate_assets["selector"]["artifacts"].append(
            {"name": "package-2.4.0.tar.gz", "sha256": DIGEST, "primary": False}
        )
        cases.append(("duplicate asset", lambda: duplicate_assets, "duplicated"))

        gitops_sha = _unit("gitops-production-ref")
        gitops_sha["selector"]["ref_commit_sha"] = OTHER_SHA
        cases.append(("GitOps SHA conflict", lambda: gitops_sha, "must equal"))

        gitops_path = _unit("gitops-production-ref")
        gitops_path["selector"]["path"] = "../production"
        cases.append(("GitOps traversal", lambda: gitops_path, "safe repository-relative"))

        publication = _unit("documentation-publication")
        publication["selector"]["publication_url"] = "http://docs.example.invalid/"
        cases.append(("insecure publication URL", lambda: publication, "HTTPS URL"))

        for name, factory, pattern in cases:
            with self.subTest(name=name):
                self.assert_invalid(factory(), pattern)

    def test_release_download_allowlist_excludes_every_nonpackage_selector(self) -> None:
        application = _unit("application-github-deployment", "app")
        package = _unit("package-github-release", "package")
        package["selector"]["artifacts"].append(
            {"name": "package-2.4.0.spdx.json", "sha256": "d" * 64, "primary": False}
        )
        documentation = _unit("documentation-publication", "docs")
        record = {
            "schema_version": GENERIC_PRODUCTION_SCHEMA,
            "standard_version": VERSION,
            "repository": REPOSITORY,
            "units": [application, package, documentation],
        }
        validated = validate_generic_production_identity(
            record,
            config=_config(["app", "package", "docs"], "Releasable-Main"),
            repository=REPOSITORY,
        )
        self.assertEqual(
            ["package-2.4.0.tar.gz", "package-2.4.0.spdx.json"],
            declared_release_asset_names(validated),
        )
        self.assertNotIn(
            application["selector"]["artifact"]["reference"],
            declared_release_asset_names(validated),
        )

    def test_active_profile_correspondence_discriminators_are_not_interchangeable(self) -> None:
        application = _unit("application-github-deployment")
        application["correspondence"] = "Production-Ref"
        self.assert_invalid(application, "Exact-Main or Releasable-Main")

        gitops = _unit("gitops-production-ref")
        gitops["correspondence"] = "Releasable-Main"
        self.assert_invalid(gitops, "must be Production-Ref")

    def test_inactive_profiles_require_approved_unambiguous_disposition(self) -> None:
        no_output = _unit("approved-no-current-output")
        no_output["selector"].pop("approved_by")
        self.assert_invalid(no_output, "missing required keys")

        expired_order = _unit("approved-no-current-output")
        expired_order["selector"]["review_date"] = "2026-07-31"
        self.assert_invalid(expired_order, "must not precede")

        output_claim = _unit("approved-no-current-output")
        output_claim["source_sha"] = SOURCE_SHA
        self.assert_invalid(output_claim, "null source_sha")

        archive = _unit("archived-retired")
        archive["selector"]["write_protected"] = False
        self.assert_invalid(archive, "write_protected")

        disposition = _unit("archived-retired")
        disposition["selector"]["disposition"] = "Retired"
        self.assert_invalid(disposition, "must match")

        ambiguous_output = _unit("archived-retired")
        ambiguous_output["selector"]["last_known_output"] = {
            "status": "none",
            "kind": "release",
            "identity": "v1.0.0",
            "reason": "Contradictory record.",
        }
        self.assert_invalid(ambiguous_output, "must not identify")

    def test_configuration_binding_and_per_unit_combination_are_strict(self) -> None:
        application = _unit("application-github-deployment", "app")
        no_output = _unit("approved-no-current-output", "experiment")
        combined = {
            "schema_version": GENERIC_PRODUCTION_SCHEMA,
            "standard_version": VERSION,
            "repository": REPOSITORY,
            "units": [application, no_output],
        }
        result = validate_generic_production_identity(
            combined,
            config=_config(["app", "experiment"], "Per-unit combination"),
            repository=REPOSITORY,
        )
        self.assertEqual(2, len(result["units"]))

        with self.assertRaisesRegex(ProductionIdentityError, "unit IDs conflict"):
            validate_generic_production_identity(
                combined,
                config=_config(["app", "different"], "Per-unit combination"),
                repository=REPOSITORY,
            )

        same_contract = deepcopy(combined)
        same_contract["units"][1] = _unit("documentation-publication", "docs")
        with self.assertRaisesRegex(ProductionIdentityError, "distinct unit correspondence"):
            validate_generic_production_identity(
                same_contract,
                config=_config(["app", "docs"], "Per-unit combination"),
                repository=REPOSITORY,
            )

        check_conflict = _unit("application-github-deployment")
        with self.assertRaisesRegex(ProductionIdentityError, "authoritative_checks conflicts"):
            validate_generic_production_identity(
                _record(check_conflict),
                config=_config(["unit"], "Releasable-Main", checks=["Different check"]),
                repository=REPOSITORY,
            )

        with self.assertRaisesRegex(ProductionIdentityError, "string array"):
            validate_generic_production_identity(
                _record(_unit("application-github-deployment")),
                config=_config(["unit"], "Releasable-Main", checks=[]),
                repository=REPOSITORY,
            )

    def test_controlled_standard_version_uses_strict_semver_syntax(self) -> None:
        invalid_versions = (
            "01.0.0",
            "1.02.3",
            "1.2.03",
            "1.2.3-",
            "1.2.3-alpha.",
            "1.2.3-alpha..1",
            "1.2.3-01",
            "1.2.3+build",
        )
        for version in invalid_versions:
            with self.subTest(version=version):
                record = _record(_unit("application-github-deployment"))
                record["standard_version"] = version
                config = _config(["unit"], "Releasable-Main")
                config["standard"]["version"] = version
                with self.assertRaisesRegex(ProductionIdentityError, "supported controlled version"):
                    validate_generic_production_identity(
                        record,
                        config=config,
                        repository=REPOSITORY,
                    )

    def test_non_object_discriminators_and_numeric_booleans_fail_cleanly(self) -> None:
        for field, value in (
            ("profile", []),
            ("lifecycle", {}),
            ("correspondence", []),
        ):
            with self.subTest(field=field):
                unit = _unit("application-github-deployment")
                unit[field] = value
                self.assert_invalid(unit)

        deployment = _unit("application-github-deployment")
        deployment["selector"]["deployment_id"] = True
        self.assert_invalid(deployment, "positive integer")

    def test_symlink_and_out_of_range_json_are_rejected(self) -> None:
        config = _config(["unit"], "Releasable-Main")
        record = _record(_unit("application-github-deployment"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "identity.json"
            target.write_text(json.dumps(record), encoding="utf-8")
            link = root / "identity-link.json"
            link.symlink_to(target)
            with self.assertRaisesRegex(ProductionIdentityError, "non-symlink"):
                load_production_identity(link, config=config, repository=REPOSITORY)

        raw = json.dumps(record).encode("utf-8")
        out_of_range = raw.replace(b'"deployment_id": 401', b'"deployment_id": 1e400')
        with self.assertRaisesRegex(ProductionIdentityError, "out-of-range JSON number"):
            load_production_identity(out_of_range, config=config, repository=REPOSITORY)


if __name__ == "__main__":
    unittest.main()

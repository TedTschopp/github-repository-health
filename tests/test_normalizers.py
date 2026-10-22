"""Offline tests for the GitHub-observation normalization boundary."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from automation.repository_health.measurements import calculate_metric_results, gate_results
from automation.repository_health.normalizers import (
    NormalizationError,
    _first_parent_history,
    _workflow_contract,
    load_production_identity,
    normalize_observations,
)


OBSERVED_AT = "2026-08-09T20:00:00Z"
REPOSITORY = "octo/repository-health"
UNIT = "repository-health"
VERSION = "1.0.0-draft"
TAG = f"v{VERSION}"
CHECK = "Validate repository"
CHECKOUT_SHA = "0123456789abcdef0123456789abcdef01234567"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run_git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _group(evidence_id: str, subject_sha: str, data: dict, *, complete: bool = True) -> dict:
    gaps = [] if complete else [
        {
            "kind": "evidence_unavailable",
            "status": 403,
            "endpoint": "/fixture",
            "source": "fixture",
            "message": "Fixture population is intentionally partial.",
        }
    ]
    return {
        "evidence_id": evidence_id,
        "observed_at": OBSERVED_AT,
        "source": f"fixture:{evidence_id}",
        "subject_sha": subject_sha,
        "unit": None,
        "state": "observed" if complete else "unknown",
        "completeness": "complete" if complete else "partial",
        "complete": complete,
        "population_complete": complete,
        "data": data,
        "gaps": gaps,
        "request": {
            "complete": complete,
            "population_complete": complete,
            "truncated": False,
        },
    }


def _result(results: list, metric_id: str):
    return next(item for item in results if item.metric_id == metric_id and item.unit_id is None)


class NormalizerFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        _run_git(root, "init", "-b", "main")
        _run_git(root, "config", "user.name", "Repository Health Test")
        _run_git(root, "config", "user.email", "health@example.invalid")

        _write(
            root,
            ".github/repository-health.toml",
            f'''[standard]
version = "{VERSION}"

[repository]
main_branch = "main"
authoritative_checks = ["{CHECK}"]
deployable_units = ["{UNIT}"]
production_correspondence = "Unknown"
''',
        )
        _write(
            root,
            ".github/workflows/validate.yml",
            f'''name: Validation workflow
on: [push, pull_request]
jobs:
  validate:
    name: {CHECK}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@{CHECKOUT_SHA}
        with:
          fetch-depth: 0
          persist-credentials: false
      - run: python -m unittest
''',
        )
        _write(root, "README.md", "source release\n")
        _run_git(root, "add", ".")
        _run_git(root, "commit", "-m", "Create source release")
        self.source_sha = _run_git(root, "rev-parse", "HEAD")
        _run_git(root, "tag", "-a", TAG, "-m", "Controlled release")
        self.tag_object_sha = _run_git(root, "rev-parse", f"{TAG}^{{tag}}")

        config_path = root / ".github" / "repository-health.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'production_correspondence = "Unknown"',
                'production_correspondence = "Releasable-Main"',
            ),
            encoding="utf-8",
        )
        self.config = {
            "standard": {"version": VERSION},
            "repository": {
                "type": "Documentation/content",
                "main_branch": "main",
                "authoritative_checks": [CHECK],
                "deployable_units": [UNIT],
                "production_correspondence": "Releasable-Main",
            },
        }
        # The signer is allowed to differ from the artifact source revision;
        # use the source revision here so the production record can itself be
        # committed and bound to the exact Main revision under assessment.
        self.main_sha = self.source_sha
        self.production, self.contents = self._production_identity()
        _write(
            root,
            ".github/repository-health-production.json",
            json.dumps(self.production, indent=2, sort_keys=True) + "\n",
        )
        _write(root, "README.md", "source release\nMain is intentionally ahead\n")
        _run_git(root, "add", ".")
        _run_git(root, "commit", "-m", "Establish production correspondence")
        self.main_sha = _run_git(root, "rev-parse", "HEAD")

        self.bundle = self._observation_bundle()
        self.local = {
            "root": str(root),
            "is_git_repository": True,
            "main_sha": self.main_sha,
            "release_asset_contents": self.contents,
            "validation_categories": ["documentation", "schema"],
            "workflow_inputs_stable": True,
            "feedback_slo_minutes": 30,
            "enforcement_tested": True,
        }

    def _production_identity(self) -> tuple[dict, dict[str, bytes]]:
        source_name = f"repository-health-{VERSION}.tar.gz"
        sbom_name = f"repository-health-{VERSION}.spdx.json"
        identity_name = f"repository-health-{VERSION}.source.json"
        source_content = b"deterministic source archive"
        sbom_content = b'{"spdxVersion":"SPDX-2.3"}\n'
        source_digest = _sha256(source_content)
        sbom_digest = _sha256(sbom_content)
        identity = {
            "schema_version": "RH-RELEASE-IDENTITY-1.0",
            "source_repository": f"https://github.com/{REPOSITORY}",
            "source_ref": f"refs/tags/{TAG}",
            "source_sha": self.source_sha,
            "standard_version": VERSION,
            # The first immutable release predates the current declaration.
            "production_correspondence": "Unknown",
            "tag": TAG,
            "artifacts": [
                {"name": source_name, "role": "source-package", "sha256": source_digest},
                {"name": sbom_name, "role": "sbom", "sha256": sbom_digest},
            ],
        }
        identity_content = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        identity_digest = _sha256(identity_content)
        checksums_content = (
            f"{source_digest}  {source_name}\n"
            f"{sbom_digest}  {sbom_name}\n"
            f"{identity_digest}  {identity_name}\n"
        ).encode("utf-8")
        attestation_content = b'{"mediaType":"application/vnd.dev.sigstore.bundle+json;version=0.3"}\n'
        contents = {
            source_name: source_content,
            sbom_name: sbom_content,
            identity_name: identity_content,
            "SHA256SUMS": checksums_content,
            "attestation.json": attestation_content,
        }
        artifacts = [
            {"name": source_name, "role": "source-package", "primary": True, "sha256": source_digest},
            {"name": sbom_name, "role": "sbom", "primary": False, "sha256": sbom_digest},
            {"name": identity_name, "role": "release-identity", "primary": False, "sha256": identity_digest},
            {"name": "SHA256SUMS", "role": "checksum-manifest", "primary": False, "sha256": _sha256(checksums_content)},
            {"name": "attestation.json", "role": "sbom-attestation-bundle", "primary": False, "sha256": _sha256(attestation_content)},
        ]
        production = {
            "schema_version": "RH-PRODUCTION-IDENTITY-1.0",
            "standard_version": VERSION,
            "repository": REPOSITORY,
            "units": [
                {
                    "unit_id": UNIT,
                    "kind": "github-release",
                    "correspondence": "Releasable-Main",
                    "selection": {
                        "strategy": "controlled-standard-version",
                        "tag_template": "v{standard.version}",
                        "allow_prerelease": True,
                        "allow_draft": False,
                        "allow_latest_alias": False,
                    },
                    "current": {
                        "supported": True,
                        "release_id": 101,
                        "release_url": f"https://github.com/{REPOSITORY}/releases/tag/{TAG}",
                        "published_at": "2026-08-09T18:00:00Z",
                        "immutable": True,
                        "tag": TAG,
                        "tag_object_sha": self.tag_object_sha,
                        "source_sha": self.source_sha,
                        "artifacts": artifacts,
                        "attestations": [
                            {
                                "kind": "github-immutable-release",
                                "covers": "protected tag object and all five release asset digests",
                            },
                            {
                                "kind": "sigstore-sbom",
                                "url": f"https://github.com/{REPOSITORY}/attestations/1",
                                "predicate_type": "https://spdx.dev/Document/v2.3",
                                "subject_name": source_name,
                                "subject_sha256": source_digest,
                                "signer_workflow": ".github/workflows/release.yml",
                                "signer_ref": "refs/heads/main",
                                "signer_sha": self.main_sha,
                            },
                        ],
                    },
                    "validation": {
                        "authoritative_checks": [CHECK],
                        "source_must_be_reachable_from_main": True,
                        "main_ahead_policy": "every-intervening-accepted-main-revision-must-pass-authoritative-checks",
                        "incomplete_history_result": "Unknown",
                    },
                    "limitations": [
                        "The first release source declared production correspondence Unknown; current Main establishes Releasable-Main after publication.",
                        "The custom SBOM attestation is not SLSA source provenance.",
                    ],
                }
            ],
        }
        return production, contents

    @staticmethod
    def _job(run_id: int, sha: str, completed_at: str, conclusion: str = "success") -> dict:
        return {
            "run_id": run_id,
            "attempt": 1,
            "complete": True,
            "population_complete": True,
            "run": {
                "id": run_id,
                "head_sha": sha,
                "event": "push",
                "status": "completed",
                "conclusion": conclusion,
                "created_at": "2026-08-09T17:00:00Z",
            },
            "jobs": [
                {
                    "id": run_id * 10,
                    "name": CHECK,
                    "status": "completed",
                    "conclusion": conclusion,
                    "completed_at": completed_at,
                }
            ],
        }

    def _rules(self) -> dict:
        required = {
            "type": "required_status_checks",
            "parameters": {"required_status_checks": [{"context": CHECK}]},
        }
        branch_rules = [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
            {"type": "pull_request"},
            required,
        ]
        tag_rules = [
            {"type": "deletion"},
            {"type": "non_fast_forward"},
        ]
        return {
            "rulesets": [
                {
                    "summary": {"id": 1},
                    "detail": {
                        "id": 1,
                        "enforcement": "active",
                        "conditions": {"ref_name": {"include": ["refs/heads/main"], "exclude": []}},
                        "rules": branch_rules,
                        "bypass_actors": [],
                    },
                },
                {
                    "summary": {"id": 2},
                    "detail": {
                        "id": 2,
                        "enforcement": "active",
                        "conditions": {"ref_name": {"include": [f"refs/tags/{TAG}"], "exclude": []}},
                        "rules": tag_rules,
                        "bypass_actors": [],
                    },
                },
            ],
            "effective_branch_rules": branch_rules,
            "branch_protection": {
                "required_pull_request_reviews": {},
                "required_status_checks": {"contexts": [CHECK]},
                "allow_deletions": {"enabled": False},
                "allow_force_pushes": {"enabled": False},
            },
        }

    def _observation_bundle(self) -> dict:
        artifacts = self.production["units"][0]["current"]["artifacts"]
        release_assets = [
            {
                "id": index + 1,
                "name": artifact["name"],
                "digest": f"sha256:{artifact['sha256']}",
            }
            for index, artifact in enumerate(artifacts)
        ]
        release = {
            "id": 101,
            "tag_name": TAG,
            "html_url": f"https://github.com/{REPOSITORY}/releases/tag/{TAG}",
            "published_at": "2026-08-09T18:00:00Z",
            "draft": False,
            "prerelease": True,
            "immutable": True,
            "assets": release_assets,
            "tag_target": {
                "object_type": "tag",
                "object_sha": self.tag_object_sha,
                "annotated": True,
                "peeled_type": "commit",
                "peeled_sha": self.source_sha,
                "peel_complete": True,
                "depth_capped": False,
            },
        }
        attempts = [
            self._job(11, self.source_sha, "2026-08-09T17:10:00Z"),
            self._job(12, self.main_sha, "2026-08-09T17:20:00Z"),
        ]
        check_run = {
            "id": 500,
            "name": CHECK,
            "head_sha": self.main_sha,
            "status": "completed",
            "conclusion": "success",
            "completed_at": "2026-08-09T17:30:00Z",
        }
        change = {
            "sha": self.main_sha,
            "committer": {"login": "octocat"},
            "commit": {"committer": {"date": "2026-08-09T17:00:00Z"}},
        }
        observations = {
            "repository_identity": _group(
                "E-GH-REPOSITORY",
                self.main_sha,
                {
                    "repository": REPOSITORY,
                    "default_branch": "main",
                    "main_branch": "main",
                    "main_sha": self.main_sha,
                },
            ),
            "check_runs": _group("E-GH-CHECK-RUNS", self.main_sha, {"check_runs": [check_run]}),
            "actions_w90": _group(
                "E-GH-ACTIONS-W90",
                self.main_sha,
                {"window": {"days": 90}, "workflow_runs": [], "run_attempts": attempts},
            ),
            "actions_w365": _group(
                "E-GH-ACTIONS-W365",
                self.main_sha,
                {"window": {"days": 365}, "workflow_runs": [], "run_attempts": attempts},
            ),
            "change_history": _group(
                "E-GH-CHANGE-HISTORY",
                self.main_sha,
                {
                    "window": {"days": 365},
                    "commits": [change],
                    "associated_pull_requests": [
                        {
                            "number": 7,
                            "merge_commit_sha": self.main_sha,
                            "merged_at": "2026-08-09T17:00:00Z",
                            "merged_by": {"login": "octocat"},
                        }
                    ],
                    "commit_pr_links": [{"commit_sha": self.main_sha, "pull_numbers": [7]}],
                    "reviews": [{"pull_number": 7, "reviews": []}],
                },
            ),
            "refs_releases": _group(
                "E-GH-REFS-RELEASES",
                self.main_sha,
                {"branches": [], "tags": [], "remote_refs": [], "releases": [release]},
            ),
            "delivery": _group("E-GH-DELIVERY", self.main_sha, {"deployments": [], "environments": []}),
            "rules": _group("E-GH-RULES", self.main_sha, self._rules()),
            "attestations": _group(
                "E-GH-ATTESTATIONS",
                self.main_sha,
                {
                    "assets": [
                        {
                            "release_id": 101,
                            "asset_id": asset["id"],
                            "name": asset["name"],
                            "digest": asset["digest"],
                            "attestations": [{"bundle": {"mediaType": "application/vnd.dev.sigstore.bundle+json;version=0.3"}}],
                        }
                        for asset in release_assets
                    ]
                },
            ),
        }
        return {
            "schema_version": "RH-GITHUB-OBSERVATIONS-1.0",
            "observed_at": OBSERVED_AT,
            "repository": REPOSITORY,
            "subject_sha": self.main_sha,
            "unit": None,
            "complete": True,
            "population_complete": True,
            "observations": observations,
            "gaps": [],
        }

    def normalize(self, *, bundle: dict | None = None, local: dict | None = None, history=None) -> dict:
        return normalize_observations(
            bundle or self.bundle,
            local or self.local,
            self.config,
            prior_history=history,
        )


class NormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = NormalizerFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _generic_unit(self, profile: str) -> dict:
        active = profile in {
            "application-github-deployment",
            "package-github-release",
            "gitops-production-ref",
            "documentation-publication",
        }
        unit = {
            "unit_id": UNIT,
            "profile": profile,
            "lifecycle": "Active",
            "correspondence": "Production-Ref" if profile == "gitops-production-ref" else "Releasable-Main",
            "source_sha": self.fixture.source_sha if active else None,
            "selector": {},
            "validation": {
                "authoritative_checks": [CHECK],
                "source_must_be_reachable_from_main": active or profile == "archived-retired",
                "main_ahead_policy": (
                    "archive-disposition-controls-current-state"
                    if profile == "archived-retired"
                    else "every-intervening-accepted-main-revision-must-pass-authoritative-checks"
                    if active
                    else "not-applicable-no-current-output"
                ),
                "system_of_record_proof_required": True,
                "incomplete_system_of_record_result": "Unknown",
            },
            "limitations": ["Fixture intentionally supplies no independent generic resolver proof."],
        }
        if profile == "application-github-deployment":
            unit["selector"] = {
                "system": "github-deployments",
                "strategy": "exact-deployment-id",
                "environment": "production",
                "deployment_id": 401,
                "required_status": "success",
                "artifact": {
                    "reference": f"ghcr.io/octo/repository-health@sha256:{'a' * 64}",
                    "sha256": "a" * 64,
                },
            }
        elif profile == "package-github-release":
            artifact = self.fixture.production["units"][0]["current"]["artifacts"][0]
            unit["selector"] = {
                "system": "github-releases",
                "strategy": "exact-release-id-and-tag",
                "release_id": 101,
                "tag": TAG,
                "allow_draft": False,
                "allow_prerelease": True,
                "artifacts": [
                    {
                        "name": artifact["name"],
                        "sha256": artifact["sha256"],
                        "primary": True,
                    }
                ],
            }
        elif profile == "gitops-production-ref":
            unit["selector"] = {
                "system": "git",
                "strategy": "exact-ref-commit-and-path",
                "production_ref": "refs/heads/production",
                "ref_commit_sha": self.fixture.source_sha,
                "path": "environments/production",
                "content_sha256": "b" * 64,
            }
        elif profile == "documentation-publication":
            unit["selector"] = {
                "system": "github-pages",
                "strategy": "exact-pages-deployment-id",
                "environment": "github-pages",
                "deployment_id": 601,
                "publication_url": "https://docs.example.invalid/",
                "content_sha256": "c" * 64,
                "required_status": "success",
            }
        elif profile == "approved-no-current-output":
            unit.update({"lifecycle": "Experimental", "correspondence": "N/A"})
            unit["selector"] = {
                "system": "governance-decision",
                "strategy": "approved-no-current-output",
                "decision_id": "DEC-42",
                "approved_by": "Architecture Review Board",
                "approved_at": "2026-08-01",
                "review_date": "2026-11-01",
                "reason": "No supported output exists.",
                "consumer_discovery": "Portfolio evidence was reviewed outside this fixture.",
            }
        elif profile == "archived-retired":
            unit.update({"lifecycle": "Archived", "correspondence": "N/A"})
            unit["selector"] = {
                "system": "governance-decision",
                "strategy": "archive-disposition",
                "disposition": "Archived",
                "decision_id": "RET-7",
                "approved_by": "Portfolio Owner",
                "effective_at": "2026-07-31",
                "last_known_source_sha": self.fixture.source_sha,
                "last_known_output": {
                    "status": "none",
                    "kind": None,
                    "identity": None,
                    "reason": "The repository never published a supported output.",
                },
                "write_protected": True,
            }
        return unit

    def _install_generic_identity(
        self,
        unit: dict,
        *,
        no_releases: bool = False,
    ) -> tuple[dict, list]:
        correspondence = unit["correspondence"]
        has_current_output = unit["profile"] not in {"approved-no-current-output", "archived-retired"}
        config = deepcopy(self.fixture.config)
        config["repository"].update(
            {
                "production_correspondence": correspondence,
                "has_current_output": has_current_output,
                "lifecycle": unit["lifecycle"],
            }
        )
        config_text = (
            f'[standard]\nversion = "{VERSION}"\n\n'
            "[repository]\n"
            'main_branch = "main"\n'
            f'authoritative_checks = ["{CHECK}"]\n'
            f'deployable_units = ["{UNIT}"]\n'
            f'production_correspondence = "{correspondence}"\n'
            f"has_current_output = {'true' if has_current_output else 'false'}\n"
            f'lifecycle = "{unit["lifecycle"]}"\n'
        )
        production = {
            "schema_version": "RH-PRODUCTION-IDENTITY-2.0",
            "standard_version": VERSION,
            "repository": REPOSITORY,
            "units": [unit],
        }
        _write(self.fixture.root, ".github/repository-health.toml", config_text)
        _write(
            self.fixture.root,
            ".github/repository-health-production.json",
            json.dumps(production, indent=2, sort_keys=True) + "\n",
        )
        _run_git(self.fixture.root, "add", ".github/repository-health.toml", ".github/repository-health-production.json")
        _run_git(self.fixture.root, "commit", "-m", f"Declare {unit['profile']} production identity")
        main_sha = _run_git(self.fixture.root, "rev-parse", "HEAD")

        bundle = deepcopy(self.fixture.bundle)
        bundle["subject_sha"] = main_sha
        for group in bundle["observations"].values():
            group["subject_sha"] = main_sha
        bundle["observations"]["repository_identity"]["data"]["main_sha"] = main_sha
        current_check = bundle["observations"]["check_runs"]["data"]["check_runs"][0]
        current_check["head_sha"] = main_sha
        for group_name in ("actions_w90", "actions_w365"):
            bundle["observations"][group_name]["data"]["run_attempts"].append(
                self.fixture._job(99, main_sha, "2026-08-09T19:30:00Z")
            )
        if no_releases:
            bundle["observations"]["refs_releases"]["data"]["releases"] = []
            bundle["observations"]["attestations"]["data"]["assets"] = []
        local = deepcopy(self.fixture.local)
        local["main_sha"] = main_sha
        normalized = normalize_observations(bundle, local, config)
        return normalized, calculate_metric_results(normalized)

    def test_all_generic_active_profiles_remain_unknown_without_profile_resolver_proof(self) -> None:
        for profile in (
            "application-github-deployment",
            "package-github-release",
            "gitops-production-ref",
            "documentation-publication",
        ):
            with self.subTest(profile=profile):
                normalized, results = self._install_generic_identity(self._generic_unit(profile))
                self.assertTrue(normalized["normalization"]["production_identity_valid"])
                self.assertEqual([], normalized["normalization"]["conflicts"])
                self.assertEqual("unknown", _result(results, "M-SPI-02S").state)
                self.assertEqual("unknown", _result(results, "M-SPI-04").state)
                current = normalized["observations"]["M-SPI-02S"]["data"]["items"]
                self.assertEqual(profile, current[0]["profile"])
                self.assertIsNone(current[0]["traceable"])

    def test_generic_governance_profiles_do_not_self_approve_na_or_archival_results(self) -> None:
        for profile in ("approved-no-current-output", "archived-retired"):
            with self.subTest(profile=profile):
                normalized, results = self._install_generic_identity(
                    self._generic_unit(profile),
                    no_releases=True,
                )
                self.assertTrue(normalized["normalization"]["production_identity_valid"])
                self.assertEqual("unknown", _result(results, "M-SPI-02S").state)
                self.assertEqual("unknown", _result(results, "M-SPI-03").state)
                self.assertEqual("unknown", _result(results, "M-CGD-02").state)
                self.assertFalse(
                    normalized["observations"]["M-SPI-03"]["data"]["no_current_supported_release"]
                )
                self.assertEqual("Unknown", gate_results(results)["G-02"]["status"])
                self.assertEqual("Unknown", gate_results(results)["G-04"]["status"])

    def _governance_fixture(
        self,
        *,
        recent: bool,
        with_pull_request: bool,
        bypass_complete: bool,
        enforcement_proven: bool = True,
        extra_reachable_shas: tuple[str, ...] = (),
    ) -> tuple[dict, list[dict]]:
        """Return the current collector shape plus exact local first-parent rows."""

        bundle = deepcopy(self.fixture.bundle)
        now = datetime.fromisoformat(OBSERVED_AT.replace("Z", "+00:00"))
        old = now - timedelta(days=800)
        current = now - timedelta(days=1) if recent else now - timedelta(days=730)
        history = [
            {
                "sha": self.fixture.source_sha,
                "accepted_at": old,
                "accepted_at_text": old.isoformat(),
            },
            {
                "sha": self.fixture.main_sha,
                "accepted_at": current,
                "accepted_at_text": current.isoformat(),
            },
        ]
        main_commit = {
            "sha": self.fixture.main_sha,
            "parents": [{"sha": self.fixture.source_sha}],
            "commit": {"committer": {"date": current.isoformat()}},
            "history_role": "reachable_from_selected_ref",
            "accepted_main_revision": None,
        }
        reachable = [main_commit] if recent else []
        reachable.extend(
            {
                "sha": sha,
                "parents": [{"sha": self.fixture.source_sha}],
                "commit": {"committer": {"date": current.isoformat()}},
                "history_role": "reachable_from_selected_ref",
                "accepted_main_revision": None,
            }
            for sha in extra_reachable_shas
        )
        pull = {
            "number": 7,
            "merge_commit_sha": self.fixture.main_sha,
            "merged_at": current.isoformat(),
            "merged_by": {"login": "octocat"},
            "base": {"ref": "main"},
            "blocked_until_final_checks_succeeded": enforcement_proven,
        }
        data = {
            "window": {
                "days": 365,
                "start": (now - timedelta(days=365)).isoformat(),
                "end": now.isoformat(),
            },
            "reachable_commits": reachable,
            "accepted_main_revisions": [],
            "accepted_main_revisions_complete": False,
            "historical_bypass_events": [],
            "historical_bypass_complete": bypass_complete,
            "most_recent_commit": main_commit,
            "most_recent_commit_basis": {
                "complete": True,
                "window_days": 365,
                "window_population_complete": True,
                "window_commit_identity_complete": True,
                "most_recent_commit_complete": True,
                "no_reachable_commits_in_window": not recent,
                "older_than_window": not recent,
                "no_reachable_commits_w365": not recent,
                "older_than_w365": not recent,
            },
            "associated_pull_requests": [pull] if with_pull_request else [],
            "commit_pr_links": [
                {
                    "commit_sha": self.fixture.main_sha,
                    "pull_numbers": [7] if with_pull_request else [],
                    "reachability_scope": "window" if recent else "most_recent",
                    "accepted_main_revision": None,
                }
            ],
            "reviews": [
                {
                    "pull_number": 7,
                    "reviews": [],
                    "complete": True,
                    "population_complete": True,
                }
            ] if with_pull_request else [],
        }
        group = bundle["observations"]["change_history"]
        group.update(
            {
                "state": "unknown",
                "completeness": "partial",
                "complete": False,
                "population_complete": False,
                "data": data,
                "gaps": [
                    {
                        "kind": "accepted_main_revision_population_unavailable",
                        "message": "Reachable history is not accepted-Main history.",
                    }
                ],
                "request": {
                    "endpoints": [
                        {"label": "reachable_commits_w365", "complete": True},
                        {"label": "most_recent_selected_ref_commit", "complete": True},
                        {"label": "associated_pull_requests", "complete": True},
                        {"label": "pull_request_reviews", "complete": True},
                    ]
                },
            }
        )
        return bundle, history

    def test_current_immutable_release_passes_g02_with_disclosed_first_release_limitation(self) -> None:
        normalized = self.fixture.normalize()
        results = calculate_metric_results(normalized)

        current = _result(results, "M-SPI-02S")
        self.assertEqual((current.state, current.band), ("measured", "Pass"))
        self.assertEqual(gate_results(results)["G-02"]["status"], "Pass")
        limitations = normalized["normalization"]["limitations"]
        self.assertTrue(any("production correspondence Unknown" in item for item in limitations))
        self.assertTrue(any("not SLSA source provenance" in item for item in limitations))
        self.assertFalse(normalized["normalization"]["assessed_repository_build_code_executed"])

    def test_main_ahead_requires_every_intervening_exact_revision_check(self) -> None:
        normalized = self.fixture.normalize()
        row = normalized["observations"]["M-SPI-04"]["data"]["items"][-1]
        self.assertNotEqual(row["production_sha"], row["main_sha"])
        self.assertTrue(row["reachable_from_main"])
        self.assertTrue(row["intervening_gates_passed"])
        self.assertEqual(set(row["intervening_revisions"]), {self.fixture.main_sha})

        partial = deepcopy(self.fixture.bundle)
        for name in ("actions_w90", "actions_w365"):
            partial["observations"][name]["data"]["run_attempts"] = [
                attempt
                for attempt in partial["observations"][name]["data"]["run_attempts"]
                if attempt["run"]["head_sha"] != self.fixture.main_sha
            ]
        partial["observations"]["check_runs"]["data"]["check_runs"] = []
        unknown = calculate_metric_results(self.fixture.normalize(bundle=partial))
        self.assertEqual(_result(unknown, "M-SPI-02S").state, "unknown")

    def test_known_release_digest_mismatch_is_a_fail(self) -> None:
        bundle = deepcopy(self.fixture.bundle)
        bundle["observations"]["refs_releases"]["data"]["releases"][0]["assets"][0]["digest"] = f"sha256:{'f' * 64}"
        results = calculate_metric_results(self.fixture.normalize(bundle=bundle))
        current = _result(results, "M-SPI-02S")
        self.assertEqual((current.state, current.band), ("measured", "Fail"))
        self.assertEqual(gate_results(results)["G-02"]["status"], "Fail")

    def test_missing_downloaded_release_content_is_unknown(self) -> None:
        local = deepcopy(self.fixture.local)
        local.pop("release_asset_contents")
        results = calculate_metric_results(self.fixture.normalize(local=local))
        self.assertEqual(_result(results, "M-SPI-02S").state, "unknown")

    def test_missing_daily_history_keeps_correspondence_unknown(self) -> None:
        results = calculate_metric_results(self.fixture.normalize(history=None))
        correspondence = _result(results, "M-SPI-04")
        self.assertEqual(correspondence.state, "unknown")
        self.assertIsNone(correspondence.band)
        self.assertTrue(
            correspondence.components["per_unit"][UNIT]["components"]["current_conforms"]
        )

    def test_ninety_validated_daily_snapshots_bootstrap_correspondence_trend(self) -> None:
        current = datetime.fromisoformat(OBSERVED_AT.replace("Z", "+00:00"))

        def history(count: int) -> list[dict]:
            snapshots: list[dict] = []
            for offset in range(count, 0, -1):
                generated_at = (current - timedelta(days=offset)).isoformat()
                snapshots.append(
                    {
                        "assessment": {
                            "generated_at": generated_at,
                            "measurements": [
                                {
                                    "metric_id": "M-SPI-04",
                                    "unit_id": UNIT,
                                    "state": "unknown",
                                    "band": None,
                                    "assurance": "E0",
                                    "components": {
                                        "current_conforms": True,
                                        "current_evidence_assurance": "E3",
                                    },
                                }
                            ],
                        }
                    }
                )
            return snapshots

        insufficient = calculate_metric_results(self.fixture.normalize(history=history(89)))
        self.assertEqual("unknown", _result(insufficient, "M-SPI-04").state)

        complete = calculate_metric_results(self.fixture.normalize(history=history(90)))
        correspondence = _result(complete, "M-SPI-04")
        self.assertEqual(("measured", "Pass"), (correspondence.state, correspondence.band))

    def test_partial_rules_keep_tag_protection_and_g04_unknown(self) -> None:
        bundle = deepcopy(self.fixture.bundle)
        rules = bundle["observations"]["rules"]
        rules.update(
            {
                "state": "unknown",
                "completeness": "partial",
                "complete": False,
                "population_complete": False,
                "gaps": [{"kind": "forbidden", "message": "Ruleset detail returned 403."}],
            }
        )
        results = calculate_metric_results(self.fixture.normalize(bundle=bundle))
        self.assertEqual(_result(results, "M-CGD-02").state, "unknown")
        self.assertEqual(gate_results(results)["G-04"]["status"], "Unknown")
        self.assertEqual(_result(results, "M-SPI-02S").state, "unknown")

    def test_exact_main_authoritative_check_pass_fail_and_missing(self) -> None:
        passing = calculate_metric_results(self.fixture.normalize())
        self.assertEqual((_result(passing, "M-SPI-01").state, _result(passing, "M-SPI-01").band), ("measured", "Pass"))

        failed_bundle = deepcopy(self.fixture.bundle)
        failed_bundle["observations"]["check_runs"]["data"]["check_runs"][0]["conclusion"] = "failure"
        failed = calculate_metric_results(self.fixture.normalize(bundle=failed_bundle))
        self.assertEqual((_result(failed, "M-SPI-01").state, _result(failed, "M-SPI-01").band), ("measured", "Fail"))

        missing_bundle = deepcopy(self.fixture.bundle)
        missing_bundle["observations"]["check_runs"]["data"]["check_runs"] = []
        for name in ("actions_w90", "actions_w365"):
            missing_bundle["observations"][name]["data"]["run_attempts"] = [
                attempt
                for attempt in missing_bundle["observations"][name]["data"]["run_attempts"]
                if attempt["run"]["head_sha"] != self.fixture.main_sha
            ]
        missing = calculate_metric_results(self.fixture.normalize(bundle=missing_bundle))
        self.assertEqual(_result(missing, "M-SPI-01").state, "unknown")

    def test_current_check_success_cannot_substitute_for_incomplete_w365_build_population(self) -> None:
        bundle = deepcopy(self.fixture.bundle)
        actions = bundle["observations"]["actions_w365"]
        actions.update(
            {
                "state": "unknown",
                "completeness": "partial",
                "complete": False,
                "population_complete": False,
                "gaps": [
                    {
                        "kind": "permission_or_api_gap",
                        "message": "Actions history is incomplete.",
                    }
                ],
            }
        )
        results = calculate_metric_results(self.fixture.normalize(bundle=bundle))
        self.assertEqual("Pass", _result(results, "M-SPI-01").band)
        self.assertEqual("unknown", _result(results, "M-BTC-01").state)

    def test_nonempty_bypass_configuration_does_not_prove_audited_bypass(self) -> None:
        bundle = deepcopy(self.fixture.bundle)
        branch_ruleset = bundle["observations"]["rules"]["data"]["rulesets"][0]["detail"]
        branch_ruleset["bypass_actors"] = [
            {"actor_id": 1, "actor_type": "Team", "bypass_mode": "pull_request"}
        ]
        results = calculate_metric_results(self.fixture.normalize(bundle=bundle))
        self.assertEqual(_result(results, "M-CGD-01").state, "unknown")
        self.assertEqual(_result(results, "M-CGD-02").state, "unknown")

    def test_first_parent_history_excludes_second_parent_merge_commits(self) -> None:
        root = self.fixture.root
        _run_git(root, "switch", "-c", "feature")
        _write(root, "feature.txt", "second-parent content\n")
        _run_git(root, "add", "feature.txt")
        _run_git(root, "commit", "-m", "Feature-side commit")
        side_sha = _run_git(root, "rev-parse", "HEAD")

        _run_git(root, "switch", "main")
        _write(root, "main-only.txt", "first-parent content\n")
        _run_git(root, "add", "main-only.txt")
        _run_git(root, "commit", "-m", "Main-side commit")
        main_side_sha = _run_git(root, "rev-parse", "HEAD")
        _run_git(root, "merge", "--no-ff", "feature", "-m", "Merge feature")
        merge_sha = _run_git(root, "rev-parse", "HEAD")

        history, complete = _first_parent_history(root, merge_sha)
        accepted = [row["sha"] for row in history]
        self.assertTrue(complete)
        self.assertIn(main_side_sha, accepted)
        self.assertIn(merge_sha, accepted)
        self.assertNotIn(side_sha, accepted)

    def test_current_rules_cannot_infer_historical_no_bypass_for_direct_revision(self) -> None:
        bundle, history = self._governance_fixture(
            recent=True,
            with_pull_request=False,
            bypass_complete=False,
        )
        with patch(
            "automation.repository_health.normalizers._first_parent_history",
            return_value=(history, True),
        ):
            normalized = self.fixture.normalize(bundle=bundle)
        result = _result(calculate_metric_results(normalized), "M-CGD-01")

        self.assertEqual("unknown", result.state)
        rows = normalized["observations"]["M-CGD-01"]["data"]["items"]
        self.assertEqual([self.fixture.main_sha], [row["final_revision"] for row in rows])
        self.assertIsNone(rows[0]["bypass_used"])
        self.assertTrue(normalized["observations"]["M-CGD-01"]["data"]["current_enforcement"])

    def test_two_year_idle_repo_passes_governance_only_with_last_audit_and_tested_enforcement(self) -> None:
        bundle, history = self._governance_fixture(
            recent=False,
            with_pull_request=True,
            bypass_complete=True,
        )
        with patch(
            "automation.repository_health.normalizers._first_parent_history",
            return_value=(history, True),
        ):
            normalized = self.fixture.normalize(bundle=bundle)
        results = calculate_metric_results(normalized)
        governance = _result(results, "M-CGD-01")
        enforcement = _result(results, "M-CGD-04")

        self.assertEqual(("measured", "Pass", "Low Sample"), (governance.state, governance.band, governance.sample_class))
        self.assertEqual(("measured", "Pass", "Low Sample"), (enforcement.state, enforcement.band, enforcement.sample_class))
        self.assertEqual("E3", governance.assurance)
        self.assertEqual("Pass", gate_results(results)["G-03"]["status"])
        governance_data = normalized["observations"]["M-CGD-01"]["data"]
        self.assertTrue(governance_data["no_events"])
        self.assertEqual([], governance_data["items"])

        untested_local = deepcopy(self.fixture.local)
        untested_local["enforcement_tested"] = False
        with patch(
            "automation.repository_health.normalizers._first_parent_history",
            return_value=(history, True),
        ):
            untested = self.fixture.normalize(bundle=bundle, local=untested_local)
        self.assertEqual("unknown", _result(calculate_metric_results(untested), "M-CGD-04").state)

    def test_complete_pr_mediated_first_parent_change_passes_governance(self) -> None:
        side_sha = "f" * 40
        bundle, history = self._governance_fixture(
            recent=True,
            with_pull_request=True,
            bypass_complete=True,
            enforcement_proven=True,
            extra_reachable_shas=(side_sha,),
        )
        with patch(
            "automation.repository_health.normalizers._first_parent_history",
            return_value=(history, True),
        ):
            normalized = self.fixture.normalize(bundle=bundle)
        results = calculate_metric_results(normalized)

        self.assertEqual(("measured", "Pass"), (_result(results, "M-CGD-01").state, _result(results, "M-CGD-01").band))
        self.assertEqual(("measured", "Pass"), (_result(results, "M-CGD-04").state, _result(results, "M-CGD-04").band))
        self.assertEqual("E3", _result(results, "M-CGD-01").assurance)
        self.assertEqual("Pass", gate_results(results)["G-03"]["status"])
        rows = normalized["observations"]["M-CGD-01"]["data"]["items"]
        self.assertEqual([self.fixture.main_sha], [row["final_revision"] for row in rows])
        self.assertNotIn(side_sha, {row["final_revision"] for row in rows})
        self.assertFalse(rows[0]["bypass_used"])

    def test_missing_validation_category_basis_is_unknown_not_na(self) -> None:
        local = deepcopy(self.fixture.local)
        local.pop("validation_categories")
        results = calculate_metric_results(self.fixture.normalize(local=local))
        category = _result(results, "M-BTC-03")
        self.assertEqual(category.state, "unknown")
        self.assertIsNone(category.band)

    def test_dirty_working_tree_workflow_cannot_change_exact_main_metric(self) -> None:
        workflow = self.fixture.root / ".github" / "workflows" / "validate.yml"
        workflow.write_text(
            "name: hostile local replacement\nsteps:\n  - uses: attacker/action@main\n",
            encoding="utf-8",
        )
        results = calculate_metric_results(self.fixture.normalize())
        replay = _result(results, "M-BTC-01")
        self.assertEqual((replay.state, replay.band), ("measured", "Pass"))

    def test_workflow_contract_is_scoped_to_the_authoritative_job(self) -> None:
        workflow = self.fixture.root / ".github" / "workflows" / "validate.yml"
        workflow.write_text(
            f'''name: Validation workflow
on: [push]
jobs:
  validate:
    name: {CHECK}
    steps:
      - uses: actions/checkout@main
  unrelated:
    name: Unrelated safe checkout
    steps:
      - uses: actions/checkout@{CHECKOUT_SHA}
        with:
          fetch-depth: 0
          persist-credentials: false
''',
            encoding="utf-8",
        )
        _run_git(self.fixture.root, "add", str(workflow.relative_to(self.fixture.root)))
        _run_git(self.fixture.root, "commit", "-m", "Add two validation jobs")
        unsafe_sha = _run_git(self.fixture.root, "rev-parse", "HEAD")
        self.assertFalse(_workflow_contract(self.fixture.root, unsafe_sha, [CHECK]))

        workflow.write_text(
            f'''name: Validation workflow
on: [push]
jobs:
  validate:
    name: {CHECK}
    steps:
      - uses: actions/checkout@{CHECKOUT_SHA}
        with:
          fetch-depth: 0
          persist-credentials: false
  unrelated:
    name: Unrelated shallow checkout
    steps:
      - uses: actions/checkout@main
''',
            encoding="utf-8",
        )
        _run_git(self.fixture.root, "add", str(workflow.relative_to(self.fixture.root)))
        _run_git(self.fixture.root, "commit", "-m", "Secure authoritative job only")
        safe_sha = _run_git(self.fixture.root, "rev-parse", "HEAD")
        self.assertTrue(_workflow_contract(self.fixture.root, safe_sha, [CHECK]))

    def test_uncommitted_metric_policy_conflict_forces_every_metric_unknown(self) -> None:
        dirty_config = deepcopy(self.fixture.config)
        dirty_config["repository"]["authoritative_checks"] = ["Uncommitted check"]
        normalized = normalize_observations(
            self.fixture.bundle,
            self.fixture.local,
            dirty_config,
        )
        results = calculate_metric_results(normalized)
        self.assertTrue(all(item.state == "unknown" for item in results))
        self.assertTrue(
            any("differs from exact Main" in item for item in normalized["normalization"]["conflicts"])
        )

    def test_supplied_production_identity_must_match_exact_main(self) -> None:
        supplied = deepcopy(self.fixture.production)
        supplied["units"][0]["limitations"].append("Uncommitted caller-only assertion.")
        normalized = normalize_observations(
            self.fixture.bundle,
            self.fixture.local,
            self.fixture.config,
            production_identity=supplied,
        )
        results = calculate_metric_results(normalized)
        self.assertTrue(all(item.state == "unknown" for item in results))
        self.assertTrue(
            any(
                "production identity differs from exact Main" in item
                for item in normalized["normalization"]["conflicts"]
            )
        )

    def test_missing_production_identity_cannot_fabricate_release_na_or_ref_pass(self) -> None:
        _run_git(self.fixture.root, "rm", ".github/repository-health-production.json")
        _run_git(self.fixture.root, "commit", "-m", "Remove production identity")
        main_sha = _run_git(self.fixture.root, "rev-parse", "HEAD")
        bundle = deepcopy(self.fixture.bundle)
        bundle["subject_sha"] = main_sha
        for group in bundle["observations"].values():
            group["subject_sha"] = main_sha
        bundle["observations"]["repository_identity"]["data"]["main_sha"] = main_sha
        check_run = bundle["observations"]["check_runs"]["data"]["check_runs"][0]
        check_run["head_sha"] = main_sha
        bundle["observations"]["refs_releases"]["data"]["releases"] = []
        bundle["observations"]["attestations"]["data"]["assets"] = []
        local = deepcopy(self.fixture.local)
        local["main_sha"] = main_sha
        normalized = normalize_observations(bundle, local, self.fixture.config)
        results = calculate_metric_results(normalized)
        self.assertEqual("unknown", _result(results, "M-SPI-03").state)
        self.assertEqual("Unknown", gate_results(results)["G-04"]["status"])

    def test_declared_no_output_and_empty_releases_cannot_self_approve_na(self) -> None:
        _run_git(self.fixture.root, "rm", ".github/repository-health-production.json")
        config_path = self.fixture.root / ".github" / "repository-health.toml"
        config_text = config_path.read_text(encoding="utf-8").replace(
            'production_correspondence = "Releasable-Main"',
            'production_correspondence = "N/A"\nhas_current_output = false',
        )
        config_path.write_text(config_text, encoding="utf-8")
        _run_git(self.fixture.root, "add", ".github/repository-health.toml")
        _run_git(self.fixture.root, "commit", "-m", "Declare no current output")
        main_sha = _run_git(self.fixture.root, "rev-parse", "HEAD")

        bundle = deepcopy(self.fixture.bundle)
        bundle["subject_sha"] = main_sha
        for group in bundle["observations"].values():
            group["subject_sha"] = main_sha
        bundle["observations"]["repository_identity"]["data"]["main_sha"] = main_sha
        bundle["observations"]["check_runs"]["data"]["check_runs"][0]["head_sha"] = main_sha
        bundle["observations"]["refs_releases"]["data"]["releases"] = []
        bundle["observations"]["attestations"]["data"]["assets"] = []
        local = deepcopy(self.fixture.local)
        local["main_sha"] = main_sha
        config = deepcopy(self.fixture.config)
        config["repository"]["production_correspondence"] = "N/A"
        config["repository"]["has_current_output"] = False

        normalized = normalize_observations(bundle, local, config)
        result = _result(calculate_metric_results(normalized), "M-SPI-03")

        self.assertEqual("unknown", result.state)
        self.assertTrue(
            any(
                "independent governance" in limitation
                for limitation in normalized["normalization"]["limitations"]
            )
        )

    def test_production_json_rejects_duplicate_and_unknown_fields(self) -> None:
        raw = json.dumps(self.fixture.production).encode("utf-8")
        loaded = load_production_identity(raw, config=self.fixture.config, repository=REPOSITORY)
        self.assertEqual(loaded["units"][0]["current"]["source_sha"], self.fixture.source_sha)

        duplicate = raw.decode("utf-8").replace(
            '"schema_version": "RH-PRODUCTION-IDENTITY-1.0",',
            '"schema_version": "RH-PRODUCTION-IDENTITY-1.0", "schema_version": "RH-PRODUCTION-IDENTITY-1.0",',
            1,
        ).encode("utf-8")
        with self.assertRaises(NormalizationError):
            load_production_identity(duplicate, config=self.fixture.config, repository=REPOSITORY)

        unknown = deepcopy(self.fixture.production)
        unknown["units"][0]["current"]["attestations"][0]["uncontrolled"] = True
        with self.assertRaises(NormalizationError):
            load_production_identity(unknown, config=self.fixture.config, repository=REPOSITORY)


if __name__ == "__main__":
    unittest.main()

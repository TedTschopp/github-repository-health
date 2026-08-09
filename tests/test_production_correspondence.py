"""Regression checks for this repository's published-unit contract."""

from __future__ import annotations

from pathlib import Path
import json
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".github" / "repository-health.toml"
RECORD = ROOT / "docs" / "release-and-production.md"
PRODUCTION = ROOT / ".github" / "repository-health-production.json"

UNIT_ID = "github-repository-health"
TAG = "v0.1.0-draft"
SOURCE_SHA = "e1fe796eb2a4e472607bc11503a2364b02818160"
ARCHIVE_SHA256 = "f6613cc472837095548d8e3b58b864e1ee6930c0366e90ca4fa942b1f34cca59"
SBOM_SHA256 = "968c153e291ba7e7ccbf51ff300c2c9b2492944e37ef46b0eca2f05e85a875c7"


class ProductionCorrespondenceTests(unittest.TestCase):
    def test_configuration_declares_one_releasable_main_unit(self) -> None:
        with CONFIG.open("rb") as stream:
            config = tomllib.load(stream)
        repository = config["repository"]

        self.assertEqual(repository["deployable_units"], [UNIT_ID])
        self.assertEqual(repository["production_correspondence"], "Releasable-Main")
        self.assertEqual(config["methodology_axes"]["release_source"], "Protected immutable version tag reachable from Main")

    def test_current_record_binds_unit_source_and_artifact_identity(self) -> None:
        with CONFIG.open("rb") as stream:
            config = tomllib.load(stream)
        production = json.loads(PRODUCTION.read_text(encoding="utf-8"))
        self.assertEqual(production["schema_version"], "RH-PRODUCTION-IDENTITY-1.0")
        self.assertEqual(production["standard_version"], config["standard"]["version"])
        self.assertEqual(len(production["units"]), 1)
        unit = production["units"][0]
        self.assertEqual(unit["unit_id"], UNIT_ID)
        self.assertEqual(unit["correspondence"], "Releasable-Main")
        self.assertEqual(unit["selection"]["strategy"], "controlled-standard-version")
        self.assertFalse(unit["selection"]["allow_latest_alias"])
        self.assertEqual(unit["current"]["tag"], f"v{config['standard']['version']}")
        self.assertEqual(unit["current"]["source_sha"], SOURCE_SHA)
        self.assertTrue(unit["current"]["immutable"])
        artifacts = {item["role"]: item for item in unit["current"]["artifacts"]}
        self.assertEqual(artifacts["source-package"]["sha256"], ARCHIVE_SHA256)
        self.assertTrue(artifacts["source-package"]["primary"])
        self.assertEqual(artifacts["sbom"]["sha256"], SBOM_SHA256)
        self.assertEqual(sum(bool(item["primary"]) for item in artifacts.values()), 1)
        validation = unit["validation"]
        self.assertEqual(validation["authoritative_checks"], ["Validate repository"])
        self.assertEqual(
            validation["main_ahead_policy"],
            "every-intervening-accepted-main-revision-must-pass-authoritative-checks",
        )
        self.assertEqual(validation["incomplete_history_result"], "Unknown")

        text = RECORD.read_text(encoding="utf-8")
        self.assertIn("GitHub's immutable flag set", text)
        self.assertIn("prove the commit is reachable from the current Main history", text)
        self.assertIn("https://spdx.dev/Document/v2.3", text)
        self.assertIn("must not be converted to Pass by this document alone", text)
        self.assertIn("every accepted Main revision", text)

    def test_record_defines_non_destructive_supersession_and_withdrawal(self) -> None:
        text = RECORD.read_text(encoding="utf-8")
        self.assertIn("without moving its tag or replacing its assets", text)
        self.assertIn("Prior releases, tags, digests, and attestations remain retained", text)
        self.assertIn("failed or interrupted publication does not change", text)


if __name__ == "__main__":
    unittest.main()

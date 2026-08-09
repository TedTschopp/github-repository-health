from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class GovernanceMetadataTests(unittest.TestCase):
    def test_required_governance_files_exist_and_are_nonempty(self) -> None:
        for relative in (
            "LICENSE",
            "SECURITY.md",
            "SUPPORT.md",
            "OWNERS.md",
            ".github/CODEOWNERS",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file(), relative)
            self.assertTrue(path.read_text(encoding="utf-8").strip(), relative)

    def test_rights_notice_does_not_claim_an_unapproved_open_source_license(self) -> None:
        text = (ROOT / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("All rights reserved", text)
        self.assertIn("No license is granted", text)

    def test_security_policy_has_a_private_route_scope_and_invariants(self) -> None:
        text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
        self.assertIn("security/advisories/new", text)
        self.assertIn("Do not open a public issue", text)
        self.assertIn("## System and scope", text)
        self.assertIn("## Threat model and trust boundaries", text)
        self.assertIn("## Security invariants", text)
        self.assertIn("fail closed to `Unknown`", text)
        self.assertIn("No issue or finding is considered accepted risk", text)

    def test_support_routes_security_away_from_public_issues(self) -> None:
        text = (ROOT / "SUPPORT.md").read_text(encoding="utf-8")
        self.assertIn("github-repository-health/issues/new", text)
        self.assertIn("Do not use a public Issue", text)
        self.assertIn("SECURITY.md", text)

    def test_codeowners_covers_default_and_critical_paths(self) -> None:
        text = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8")
        for entry in ("* @TedTschopp", "/.github/", "/automation/", "/docs/"):
            self.assertIn(entry, text)

    def test_ownership_names_accountability_and_continuity_gap(self) -> None:
        text = (ROOT / "OWNERS.md").read_text(encoding="utf-8")
        self.assertIn("Enterprise Architecture", text)
        self.assertIn("@TedTschopp", text)
        self.assertIn("Backup owner", text)
        self.assertIn("Not yet assigned", text)


if __name__ == "__main__":
    unittest.main()

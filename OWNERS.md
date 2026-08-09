# Repository Ownership

## Accountabilities

| Area | Accountable owner | Responsibilities |
| --- | --- | --- |
| Normative standard and scoring policy | Enterprise Architecture; current maintainer [@TedTschopp](https://github.com/TedTschopp) | Approves controls, measures, methodology profiles, thresholds, gates, versions, and pilot disposition. |
| Repository and assessment automation | [@TedTschopp](https://github.com/TedTschopp) | Maintains code, workflows, tests, reports, configuration, and repository settings. |
| Security response | [@TedTschopp](https://github.com/TedTschopp) | Triages private vulnerability reports, coordinates remediation and disclosure, and records accepted risk. |
| Releases and published identity | [@TedTschopp](https://github.com/TedTschopp) | Authorizes immutable version tags, release artifacts, attestations, and withdrawal or supersession. |
| Backup owner | Not yet assigned | This is an explicit continuity risk; no alternate currently has documented authority. |

GitHub's enforceable path ownership is recorded in
[`.github/CODEOWNERS`](.github/CODEOWNERS). Repository ownership does not by
itself waive required pull-request ingress, validation, or evidence rules.

## Critical paths

The following paths require deliberate owner review because they can change the
meaning, integrity, or distribution of an assessment:

- `docs/repository-health-standard.md`, `docs/control-catalog.md`,
  `docs/measurement-dictionary.md`, and
  `docs/scoring-assurance-exceptions.md`;
- `automation/repository_health/`;
- `.github/actions/`, `.github/workflows/`, and
  `.github/repository-health.toml`;
- `SECURITY.md`, `SUPPORT.md`, `LICENSE`, `OWNERS.md`, and
  `.github/CODEOWNERS`; and
- release manifests, generated schema contracts, and pilot disposition records.

## Escalation and review

Security-sensitive reports follow [SECURITY.md](SECURITY.md). Other questions
and defects follow [SUPPORT.md](SUPPORT.md). Normative decisions follow
[CONTRIBUTING.md](CONTRIBUTING.md).

Review this ownership record at least every 90 days and after any maintainer,
release process, or repository-visibility change. The next scheduled review is
2026-11-07. Assigning and validating a backup owner is the highest open
ownership-continuity action.

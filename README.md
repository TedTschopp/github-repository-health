# Git Repository Health Standard

**Version:** 0.1.0-draft

**Status:** Provisional; ready for desk calibration and controlled pilot

**Owner:** Enterprise Architecture
**Published:** 2026-08-09

This repository defines an enterprise, methodology-neutral way to classify and assess Git repository health. It is an improvement diagnostic: it makes risks and evidence visible, supports comparison within appropriate contexts, and gives maintainers a prioritized path to improve. It is not a release gate, certification, or substitute for engineering judgment.

The central contract is simple:

1. **Main is healthy.** The canonical integration branch is buildable, validated, and releasable for the repository type.
2. **Production is identifiable.** For every deployable or publishable unit, each current production or published artifact is traceable to an immutable revision reachable from Main.
3. **Change is controlled.** Changes reaching Main follow an attributable, auditable path.
4. **Critical refs are protected.** Main and every other production-critical ref are protected against unauthorized change, deletion, and history rewrite.

`Main` names a role, not necessarily a literal branch. A repository can map `master`, `trunk`, or another declared ref to that role. Main HEAD may be ahead of production when the deployed revision is known and the lag is visible, intentional, and measured.

## Start here

| Need | Document |
| --- | --- |
| Understand the standard and mandatory outcomes | [Repository Health Standard](docs/repository-health-standard.md) |
| Classify a repository and its Git methodology | [Classification Guide](docs/classification-guide.md) |
| Look up a normative control | [Control Catalog](docs/control-catalog.md) |
| Calculate or interpret a measure | [Measurement Dictionary](docs/measurement-dictionary.md) |
| Calculate the grade and evidence confidence | [Scoring, Assurance, and Exceptions](docs/scoring-assurance-exceptions.md) |
| Conduct a manual assessment | [Assessment Guide](docs/assessment-guide.md) |
| Run a recurring automated assessment | [Automated Assessment Guide](docs/automation-guide.md) |
| Integrate or exchange assessment artifacts consistently | [Documentation Artifact Schemas](docs/artifact-schemas.md) |
| Run or govern the controlled pilot | [Governance and Pilot](docs/governance-and-pilot.md) |
| Prepare the real pilot cohort | [Field Pilot Package](pilot/README.md) |
| Report pilot acceptance, sensitivity, and exit decisions | [Field Pilot Report Template](pilot/pilot-report-template.md) |
| Understand trial restrictions and known limitations | [Trial-Use Guide](docs/trial-use-guide.md) |
| Review terminology | [Glossary](docs/glossary.md) |
| See the external framework crosswalk | [Source Register](docs/source-register.md) |
| Compare fictional assessments | [Worked Assessments](examples/worked-assessments.md) |

The editable manual workbook is [Repository Health Assessment Workbook](outputs/019fe7a6-29f3-7bb2-b5de-0609ceba0945/repository-health-assessment-v0.1.xlsx). Markdown templates are available in [`templates/`](templates/).

The normative assessment set is the [Repository Health Standard](docs/repository-health-standard.md), [Control Catalog](docs/control-catalog.md), and [Scoring, Assurance, and Exceptions](docs/scoring-assurance-exceptions.md). The standard governs scope, taxonomy, the Main/production contract, domains, and gate meaning; the catalog governs control-specific requirements; and the scoring guide governs ratings, calculations, assurance, N/A, equivalence, exceptions, and result disposition. Supporting guides and templates must be interpreted consistently with that set.

## Assessment output

Every assessment reports all of the following; the aggregate score is never presented alone:

- Repository type, lifecycle state, risk tier, and deployable units.
- Declared and observed methodology, contradictions, and confidence.
- A 0–100 diagnostic score, letter grade, and named maturity level.
- Eight dimension scores and foundational-gate results.
- Evidence assurance from E0 (Unknown) through E4 (Sustained effectiveness).
- Exceptions, raw evidence references, and prioritized findings.
- A separate DORA outcome panel when reliable deployment data exists.

## Current status

Version 0.1.0-draft is a provisional documentation baseline. Its formulas and fictional worked cases can be desk-tested, but the thresholds are not enterprise-calibrated until the 12-repository, two-assessor pilot in the [Governance and Pilot](docs/governance-and-pilot.md) document is completed and approved by Enterprise Architecture. Assessment reports must disclose this status.

## Recurring automated assessment

The repository now includes a read-only assessment engine and GitHub composite action. A scheduled run produces:

- `repository-health-assessment.json`, containing facts, evidence, all 35 control results, dimensions, gates, score, assurance, findings, limitations, and the separate DORA panel;
- `health-assessment.md`, for engineers and repository owners;
- `leadership-summary.md`, written for a nontechnical audience with up to seven next actions in priority order; and
- `leadership-summary.json`, for later portfolio aggregation.

Start with the [Automated Assessment Guide](docs/automation-guide.md), the local [scheduled workflow](.github/workflows/repository-health.yml), and the [consumer workflow example](examples/workflows/repository-health.yml). Repository-specific applicability and evidence references live in `.github/repository-health.toml`.

Version tags invoke the separate [attested release workflow](.github/workflows/release.yml). It publishes a revision-bound source package, SPDX SBOM, source-identity record, checksum manifest, and GitHub artifact-attestation bundle only after the tagged revision is proven reachable from Main and validated by the authoritative check.

The automation never treats an inaccessible setting or missing record as healthy. It does not execute repository-owned code, change settings, remediate findings, deploy software, or fail a workflow because the provisional grade is low. GitHub-only evidence cannot fully prove production, operational, security, or portfolio controls; those remain Unknown until acceptable evidence is connected or supplied.

## Security, support, ownership, and rights

Report suspected vulnerabilities privately through [SECURITY.md](SECURITY.md); use [SUPPORT.md](SUPPORT.md) for ordinary questions and defects. Accountabilities, critical paths, and the current backup-owner gap are recorded in [OWNERS.md](OWNERS.md) and enforced path ownership is declared in [`.github/CODEOWNERS`](.github/CODEOWNERS).

The repository is publicly visible, but its contents are not open-source licensed. See the [All Rights Reserved Notice](LICENSE) before copying, modifying, or distributing the material.

## Versioning and contributions

Normative changes follow [CONTRIBUTING.md](CONTRIBUTING.md) and are recorded in [CHANGELOG.md](CHANGELOG.md). External references are pinned in the source register and reviewed on their documented cadence.

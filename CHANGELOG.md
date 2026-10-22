# Changelog

All material changes to the Git Repository Health Standard are recorded here. The format follows the intent of Keep a Changelog; the standard itself uses semantic versioning with an explicit draft or trial status.

## 0.1.0-draft - 2026-08-09

### Added

- Provisional repository-health standard and glossary.
- Repository-type and Git-methodology classification guide.
- Versioned control catalog across eight health dimensions.
- Measurement and evidence dictionary.
- Scoring, assurance, risk-tier, and exception policy.
- Manual assessment templates and workbook.
- Fictional worked assessments.
- Architecture-owned governance, pilot, calibration, appeal, and trial-use guidance.
- Read-only, standard-library repository-health assessment engine.
- Reusable GitHub composite action and scheduled/manual workflow.
- Structured assessment JSON, detailed Markdown assessment, and plain-language leadership reports.
- Deterministic prioritization of up to seven next actions without using the provisional score as a build gate.
- Conservative TOML configuration and evidence overrides with explicit Unknown and N/A handling.
- Fail-closed configuration validation, whole-control N/A safeguards, and explicit dirty/non-Main source-state limitations.
- Evidence-first leadership wording for Unknown controls and Markdown-safe rendering of repository-controlled text.
- Required `Validate repository` check, active Main and immutable-version-tag rulesets, and protected pull-request ingress.
- Rights, security, support, accountable ownership, CODEOWNERS, and private vulnerability-reporting records.
- Revision-bound repeatable release builder, SPDX 2.3 SBOM, SHA-256 identity manifest, isolated GitHub Release workflow, and artifact attestation.
- Paginated, read-only GitHub observation collectors for checks, Actions attempts/jobs, accepted changes, refs, releases, deployments, effective rules, security results, attestations, and workflow dependencies.
- Fail-closed `RH-GITHUB-OBSERVATIONS-1.0` normalization and `RH-METRIC-RESULT-1.0` repository/unit measurement results, including explicit population coverage, freshness, assurance, No Events, and Unknown handling.
- Detailed measurement-result reporting beneath the aggregate score and control results.
- Checksummed, append-only assessment history on an isolated `repository-health-evidence` branch with immutable snapshot paths, non-force updates, and a verifiable SHA-256 chain.
- Schema-bound workflow evidence producer and validation-workflow packaging for explicit validation, security, release, and deployment outcomes.
- Exact-Main `RH-EVIDENCE-POLICY-1.0`, Actions population contracts, and deterministic exact-subject run selection before an evidence artifact can be inspected.
- Bounded untrusted-ZIP collection, authoritative source/result/artifact/category joins, and collector-owned statement-verification projections retained as audit evidence without implicit control or score credit.
- Generic `RH-PRODUCTION-IDENTITY-2.0` per-unit profiles and a pure fail-closed delivery resolver as groundwork for heterogeneous delivery systems; generic G-02 metric mapping remains pending.

### Status

- Documentation complete for desk review.
- Automation available for diagnostic preview and offline testing.
- Producer artifacts can be selected and inventoried automatically, but no producer statement changes a metric or score until a metric-specific resolver is approved.
- Generic production identity v2 is validation and resolver groundwork; type-specific adapter-to-metric integration remains Unknown by default.
- Real 12-repository, two-assessor calibration pending.
- Not approved as a compliance or release gate.

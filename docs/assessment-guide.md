# Manual Assessment Guide

**Standard version:** 0.1.0-draft

**Status:** Provisional

This controlled supporting guide explains how to conduct a reproducible assessment without automation. Use it with the assessment workbook and the Markdown templates. The [normative assessment set and precedence](repository-health-standard.md#normative-document-set-and-precedence) govern assessment outcomes.

## Assessor conduct

- Assess observable outcomes, not preferred tools or workflow fashions.
- Record evidence before assigning conformance.
- Separate what is documented, configured, demonstrated, and sustained.
- Do not treat repository files, commits, releases, deployments, and observed production state as interchangeable evidence.
- Mark missing evidence `Unknown`; do not infer a pass.
- Use `N/A` only when the control's applicability rule excludes the repository or deployable unit and the assessor records a rationale.
- Do not remediate the repository during an assessment. Record the finding and recommended outcome.

## Required inputs

Before assessment, obtain read-only access or exported evidence for the applicable systems:

- Authoritative Git repository and hosting-platform settings.
- CI histories and required-check configuration.
- Artifact or package registry records.
- Deployment and environment records.
- Dependency, vulnerability, secret, and supply-chain evidence.
- Ownership, incident, rollback, and lifecycle records.
- The repository's declared workflow and production-correspondence policy.

If access is unavailable, record the source as unavailable and score the affected evidence as Unknown.

## Assessment sequence

### 1. Establish identity and scope

Record the repository URL, authoritative status, owner, lifecycle, criticality, risk tier, data sensitivity, applicable policy, and assessment date. Identify each independently released or deployed unit. A monorepo can therefore have several production identities and measurement populations.

### 2. Classify repository type

Apply the decision rules in the [Classification Guide](classification-guide.md). Select one primary type and any secondary facets. Mirrors, forks, sandboxes, templates, and archives remain assessable but use type-specific applicability.

### 3. Classify workflow

Complete the methodology worksheet from declarations and observed history. Record every workflow axis from the classification guide: canonical integration topology, change ingress, branch purpose and lifetime, integration cadence, release source, promotion mechanism, parallel support, control placement, and repository topology. Report a named profile only when the evidence supports it. Use `Custom/hybrid` only for understood behavior that intentionally combines profiles or fits none; when evidence is insufficient, record `Unknown` or `Unclassified` with Low confidence. Record contradictions and confidence.

### 4. Evaluate foundational gates first

Evaluate G-01 through G-04 before calculating other controls. A failed or Unknown applicable gate caps the result at 69/D/Developing. Continue the assessment so the team receives a complete diagnostic.

### 5. Assess controls and evidence

For every applicable control:

1. Copy the control ID and requirement into the assessment record.
2. Link or describe evidence with source, observation date, and covered population.
3. Assign assurance E0 through E4.
4. Assign conformance: Unmet (0), Partially met (0.5), or Met (1).
5. Record N/A rationale or exception ID where applicable.
6. Add a finding when the result is Unmet, Partially met, Unknown, stale, contradictory, or excepted.

An assessor may not assign `Met` unless the evidence reaches the minimum specified by the control. Exemplary practices are narrative observations in 0.1.0-draft and add no points.

### 6. Calculate and review the result

Use the scoring policy or workbook formulas. Review:

- Applicable points and exclusions in each dimension.
- Gate cap behavior.
- Evidence coverage and assurance.
- The aggregate score, grade, maturity, and dimension profile.
- Findings sorted by gate, risk, evidence gap, and improvement effort.

The reviewer must be able to trace every displayed score back to control-level inputs.

### 7. Complete the DORA outcome panel

When reliable deployment data exists, report the five current DORA measures per application or service and show trend over time. Do not blend these measures into the repository-health score or use them to rank unlike applications.

### 8. Review with the repository owner

Validate facts, not preferences. Owners may supply missing evidence, identify a legitimate N/A case, request an equivalent-control determination, or appeal an interpretation. Record changes and preserve the original assessor rationale.

### 9. Finalize

The final report must include the standard version, pilot status, assessor, reviewer, evidence cutoff date, classification, score profile, assurance, gates, exceptions, DORA panel, findings, and next review date.

## Finding priority

Use this order:

1. Failed or Unknown foundational gates.
2. Critical-tier control failures and expired exceptions.
3. High-risk gaps with demonstrated exposure.
4. Repeated CI, release, security, or operational failures.
5. Evidence gaps that prevent a reliable conclusion.
6. Remaining maintainability and usability improvements.

Activity volume alone is not a finding. A stable repository with few changes can be healthy when ownership, validation, vulnerability response, release traceability, and lifecycle intent remain current.

## Quality check

Before issuing a report, confirm that:

- All applicable controls have evidence, conformance, and assurance values.
- All N/A results have a rationale.
- All Unknown foundational gates caused the grade cap.
- The scorecard and detailed controls reconcile.
- Connected evidence is fresh enough for the measure.
- Contradictory declarations and observations are visible.
- DORA results are separate.
- The report states that 0.1.0-draft is provisional until the field pilot is approved.
